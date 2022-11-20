import os
import math
from time import sleep
from datetime import datetime, timedelta
import pandas as pd
import requests as rq
from flask_restful import abort
from database import (and_, app, AssetAllocation, Balance, Connection, 
                      Currency, db_session, e,
                      Exchange, ExPair,
                      func, IndexPair, or_, Transaction)


API_RETRIES = 3
GRACE_TIME = 5

_cryptobal_url = os.getenv('CRYPTOBAL_URL')
_exapi_url = os.getenv('EXAPI_URL')


def asset_allocations(cube):

    asset_alls = AssetAllocation.query.filter_by(
                    cube_id=cube.id).join(Currency, 
                    AssetAllocation.currency).order_by(
                    Currency.symbol).all()
    if asset_alls:
        assets = []
        for asset in asset_alls:
            if asset.percent:
                assets.append({'name': asset.currency.symbol,
                               'y': float(asset.percent)})              
    else:
        assets = None
    return assets


def asset_allocations_set(cube, allocations):
    symbols = []
    total = 0

    for a in allocations:
        total += a['y']

    for a in allocations:

        symbols.append(a['name'])
        currency = Currency.query.filter_by(symbol=a['name']).first()
        allocation = AssetAllocation.query.filter_by(cube_id=cube.id, currency=currency).first()

        if allocation:
            allocation.percent = a['y'] / total
        else:
            new_allocation = AssetAllocation(
                            cube_id = cube.id,
                            currency = currency,
                            percent = a['y'] / total
                        )

            new_allocation.save_to_db()


    for symbol in cube.allocations:
        if not symbol in symbols:
            allocation = AssetAllocation.query.join(Currency).filter(
                                AssetAllocation.cube_id==cube.id, 
                                Currency.symbol==symbol
                            ).first()
            allocation.percent = 0


    cube.reallocated_at = datetime.utcnow()
    cube.save_to_db()


    cube.log_user_action("Portfolio updated", str(allocations))
                
    return {'message': 'Allocations successfully updated'}

def asset_allocations_from_balances(balances, cube=None):
    if cube:

        alloc = AssetAllocation.query.filter_by(cube_id=cube.id).first()
        print(alloc)
        if not alloc:
            for bal in balances['values']:
                cur = Currency.query.filter_by(symbol=bal[0]).first()
                a = AssetAllocation(
                        cube_id=cube.id,
                        currency_id=cur.id,
                        percent=float(bal[8])
                    )
                db_session.add(a)
            db_session.commit()

    assets = []
    for bal in balances['values']:
        if bal[8] > 0:
            assets.append({'name': bal[0],
                               'y': float(bal[8])})
    print(assets)
    return assets

def asset_allocations_from_balances_all(balances, cube=None):
    if cube:

        alloc = AssetAllocation.query.filter_by(cube_id=cube.id).first()
        print(alloc)
        if not alloc:
            for bal in balances['values']:
                cur = Currency.query.filter_by(symbol=bal[0]).first()
                a = AssetAllocation(
                        cube_id=cube.id,
                        currency_id=cur.id,
                        percent=float(bal[5])
                    )
                db_session.add(a)
            db_session.commit()

    assets = []
    for bal in balances['values']:
        if bal[5] > 0:
            assets.append({'name': bal[0],
                               'y': float(bal[5])})
    print(assets)
    return assets


def create_series_chart(df):
    df.index = (df.index.values.astype(float) / 1000000).astype(float)
    return [list(p) for p in df.iteritems() if not math.isnan(p[1])]


def get_balance_data(user, cubes):
    app.logger.debug("Start get_balance_data()")
    app.logger.debug(datetime.utcnow())
    # Child rows for per exchange balances
    bals = [(b.currency.symbol, b.cube.name, float(b.total)) for cube in cubes
            for b in cube.balances if (b.total > 9e-8) or (b.currency.symbol == 'BTC')]
    bals = pd.DataFrame(bals, columns=['Asset', 'Exchange', 'Balance'])
    bals = bals.pivot(index='Asset', columns='Exchange', values='Balance')
    # # Multiply the performance by the exchanges to get a weighed performance value
    bals['Total'] = bals.sum(axis=1)
    bals = bals.fillna('-')
    bals = bals.applymap(lambda x: '%.8f' % x if type(x) is float else x)

    total_bals = bals.Total
    total_bals = total_bals.to_frame()

    btc_rate = []
    for symbol in total_bals.index:
        app.logger.debug(symbol)
        # Get ex_pair
        if symbol == 'BTC':
            btc_rate.append(1)
        else:
            cur = Currency.query.filter_by(symbol=symbol).first()
            print(cur)
            if not cur:
                btc_rate.append(0)
                continue
            index_pair = IndexPair.query.filter_by(quote_symbol='BTC',
                                                   base_currency_id=cur.id,
                                                   active=True).first()

            print(index_pair)

            if not index_pair:
                index_pair = IndexPair.query.filter_by(quote_symbol=symbol,
                                                       base_symbol='BTC',
                                                       active=True).first()
                print(index_pair)

                if not index_pair:
                    print('No index for', symbol)
                    btc_rate.append(0)
                    continue

                try:
                    btc_fiat = index_pair.index_pair_close[0].close
                except:
                    btc_fiat = 0

                if btc_fiat > 0:
                    rate = round(1 / btc_fiat, 8)
                else:
                    rate = 0
                print(rate)
                btc_rate.append(rate)
            else:
                try:
                    rate = index_pair.index_pair_close[0].close
                except:
                    rate = 0
                print(rate)
                btc_rate.append(rate)
            app.logger.debug(index_pair)
    app.logger.debug("Retrieved BTC rates")
    app.logger.debug(datetime.utcnow())
    app.logger.debug(btc_rate)

    # Find btc_fiat rate if not in bals
    fiat = IndexPair.query.filter_by(
        base_symbol='BTC',
        quote_currency_id=user.fiat_id
    ).first()
    try:
        selected_btc_fiat = fiat.index_pair_close[0].close
    except:
        selected_btc_fiat = 0


    total_bals['BTC_Rate'] = btc_rate
    total_bals[['Total', 'BTC_Rate']] = total_bals[['Total', 'BTC_Rate']].astype(float)

    total_bals['BTC_Value'] = total_bals.Total.multiply(total_bals.BTC_Rate)

    total_bals['Fiat_Value'] = total_bals.BTC_Value.multiply(float(selected_btc_fiat))

    total_btc = total_bals.BTC_Value.sum()
    total_bals['Percent_of_Portfolio'] = total_bals.BTC_Value.divide(total_btc)


    def target_mapper(bal):
        for cube in cubes:
            if bal.name in cube.allocations:
                return float(cube.allocations[bal.name].percent)
            else:
                return 0

    total_bals['Target'] = total_bals.apply(target_mapper, axis=1)


    def percent_off_mapper(bal):
        for cube in cubes:
            if bal.name in cube.allocations:
                target = float(cube.allocations[bal.name].percent)
            else:
                target = 0
            if target == 0:
                return 0
            return (bal.Percent_of_Portfolio - target) / target

    total_bals['Percent_Off_Goal'] = total_bals.apply(percent_off_mapper, axis=1)


    total_btc = total_bals.BTC_Value.sum()
    total_fiat = total_bals.Fiat_Value.sum()


    total_bals = total_bals[total_bals.Fiat_Value >= 1].copy()

    header = total_bals.columns.tolist()
    total_bals = total_bals.reset_index()
    total_bals = total_bals.fillna(0)
    values = total_bals.values.tolist()


    balances = {}
    balances['header'] = header or []
    balances['values'] = values or []


    total = {}
    total['btc'] = total_btc or 0
    total['fiat'] = total_fiat or 0
    app.logger.debug("End get_balance_data()")
    app.logger.debug(datetime.utcnow())
    return balances, total


def get_balance_data_single(cube):

    bals = [(b.currency.symbol,
             float(b.total),
             float(b.btc_rate),
             b.currency.percent_change_1h / 100 if b.currency.percent_change_1h else 0,
             b.currency.percent_change_24h / 100 if b.currency.percent_change_24h else 0,
             b.currency.percent_change_7d / 100 if b.currency.percent_change_7d else 0)
            for b in cube.balances if (b.total > 9e-8) or (b.currency.symbol == 'BTC')]


    bals = pd.DataFrame(bals, columns=['Asset', 'Balance', 'BTC_Rate', '1h_BTC_Change', '1d_BTC_Change', '1w_BTC_Change'])
    bals = bals.fillna('-')
    print(bals)


    bals['BTC_Value'] = bals.Balance.multiply(bals.BTC_Rate)


    fiat = ExPair.query.filter_by(
        base_symbol='BTC'
    ).first()
    print(fiat)
    print(fiat.ex_pair_close[0].close)
    try:
        selected_btc_fiat = fiat.ex_pair_close[0].close
    except:
        selected_btc_fiat = 0
    bals['Fiat_Value'] = bals.BTC_Value.multiply(float(selected_btc_fiat))

    total_btc = bals.BTC_Value.sum()
    bals['Percent_of_Portfolio'] = bals.BTC_Value.divide(total_btc)


    def target_mapper(bal):
        if bal.Asset in cube.allocations:
            return float(cube.allocations[bal.Asset].percent)
        else:
            return 0

    bals['Target'] = bals.apply(target_mapper, axis=1)


    def percent_off_mapper(bal):
        if bal.Asset in cube.allocations:
            target = float(cube.allocations[bal.Asset].percent)
        else:
            target = 0
        if target == 0:
            return 0
        return (bal.Percent_of_Portfolio - target) / target

    bals['Percent_Off_Goal'] = bals.apply(percent_off_mapper, axis=1)


    total_btc = bals.BTC_Value.sum()
    total_fiat = bals.Fiat_Value.sum()


    bals = bals[bals.Fiat_Value >= 1].copy()

    header = bals.columns.tolist()
    bals = bals.fillna(0)
    values = bals.values.tolist()

    # Balances
    balances = {}
    balances['header'] = header or []
    balances['values'] = values or []

    # Totals
    total = {}
    total['btc'] = total_btc or 0
    total['fiat'] = total_fiat or 0

    return balances, total


def get_ex_assets(cube):
    ex_assets = {}
    for c in cube.connections.values():
        if not c.failed_at:
            asset_list = []
            ex_pairs = ExPair.query.filter_by(
                            exchange_id=c.exchange_id).all()
            for pair in ex_pairs:
                if pair.quote_currency.symbol not in asset_list:
                    asset_list.append(pair.quote_currency.symbol)
                if pair.base_currency.symbol not in asset_list:
                    asset_list.append(pair.base_currency.symbol)
            ex_assets[c.exchange.name] = asset_list

    return ex_assets


def get_fiat_allocation(cube):
    if (cube.allocations and 
        cube.fiat.symbol in cube.allocations and not 
        cube.allocations[cube.fiat.symbol] is None):
        fiat_allocation = int(cube.allocations[cube.fiat.symbol].percent)
    else:
        fiat_allocation = 0
    return fiat_allocation


def get_request(endpoint, exchange, key, secret, passphrase=None):
    for i in range(API_RETRIES + 1):
        try:
            url = _exapi_url + '/' + exchange + endpoint
            app.logger.debug(url)
            params = {'key' : key, 'secret' : secret, 'passphrase': passphrase}
            r = rq.get(url, params=params)
            app.logger.debug(r.url)
            app.logger.debug(r.status_code)
            r.raise_for_status()
            if r.status_code == 200:
                json_content = r.json()
                app.logger.debug(json_content)
                return json_content
        except Exception as e:
            if i == API_RETRIES:
                return None
            app.logger.exception(e)
            sleep(GRACE_TIME)


def process_key_exception(e, ex_id, cube):
    err = e.args[0]
    if type(err).__name__ == 'APIError':
        app.logger.exception(err)
    elif type(err).__name__ == 'APIKeyError':
        app.logger.exception('%s Invalid API key/secret for Ex_ID %s: %s' % (str(cube), ex_id, err))
    elif type(err).__name__ == 'ConnectionError':
        app.logger.exception('%s Invalid API key/secret for Ex_ID %s: %s' % (str(cube), ex_id, err))
    else:
        app.logger.exception('[%s] %s' % (cube, err))
    return False


def test_key(cube, ex_id, key, secret, passphrase):
    ex_name = Exchange.query.filter_by(id=ex_id).first().name
    # Check for balances
    try:
        bals = get_request('/balances', ex_name, key, secret, passphrase)
        app.logger.debug(bals)
    except Exception as e:
        message = 'Exception while querying balances.'
        return process_key_exception(e, ex_id, cube), message

    if not bals:
        app.logger.warning('No balances for Ex_ID %s' % (ex_id))
        message = 'You have no balances. Please deposit funds and try again.'
        return False, message

    # Look for non-zero balances for Coinbase Pro accounts
    for bal in bals.values():
        if bal['total']:
            break  
    else:
        message = 'You have no balances. Please deposit funds and try again.'
        return False, message

    # Check for trade permission
    try:
        if not get_request('/trade/test', ex_name, key, secret, passphrase):
            message = 'API key trading is not enabled.'
            return False, message
    except Exception as e:
        message = 'Exception while querying trading permissions.'
        return process_key_exception(e, ex_id, cube), message

    # Test for withdrawal permission
    try:
        if get_request('/withdrawal/test', ex_name, key, secret, passphrase):
            message = 'API keys have withdrawal/transfer enabled. Please remove this permission and try again.'
            return False, message
    except Exception as e:
        message = 'Exception while querying withdrawal permissions.'
        return process_key_exception(e, ex_id, cube), message

    # All is correct, return True
    return True, 'Keys are configured correctly.'


def add_key(cube, ex_id, key, secret, passphrase):
    app.logger.debug('[%s] Adding keys' % (cube))
    # Add initial transactions to database
    if add_balances(ex_id, key, secret, passphrase, cube):
        try:
            # Encrypt keys and add connection
            conn = Connection(
                user_id=cube.user_id,
                cube_id=cube.id,
                exchange_id=ex_id,
                key=e(key),
                secret=e(secret),
                passphrase=e(passphrase)
                )
            conn.save_to_db()
            app.logger.info('[%s] Added API key for Ex_ID: %s' % (cube, ex_id))
            message = 'API keys added successfully. Exchange connection is live!'
            cube.log_user_action("save_api_keys")
            cube.update_charts = 1
            cube.save_to_db()
            return message
        except Exception as error:
            app.logger.debug('[%s] Trouble adding API key for Ex_ID: %s' % (cube, ex_id))
            app.logger.debug(error)
            remove_balances(ex_id, cube)
            db_session.delete(cube)
            db_session.commit()
            raise
    else:
        remove_balances(ex_id, cube)
        db_session.delete(cube)
        db_session.commit()
        message = 'There was a problem adding your API keys.'
        return message


def update_key(cube, ex_id, key, secret, passphrase):
    remove_balances(ex_id, cube)
    Connection.query.filter_by(
            cube_id=cube.id,
            exchange_id=ex_id).update({'key': e(key),
                                       'secret': e(secret),
                                       'passphrase': e(passphrase),
                                       'failed_at': None
                                       })
    # Add initial transactions to database
    if add_balances(ex_id, key, secret, passphrase, cube):
        # Generate cube daily performance and update account performance
        message = 'API keys were updated successfully. Exchange connection is live!'
        cube.log_user_action("save_api_keys")
        cube.update_charts = 1
        cube.save_to_db()
        return message
    else:
        remove_balances(ex_id, cube)
        message = 'There was a problem updating your API keys.'
        abort(500, message=message)


def remove_key(cube, ex_id):
    app.logger.debug('[%s] Removing keys for Ex_ID: %s' % (cube, ex_id))
    try:
        # Add withdraw tx and remove balances
        add_txs(ex_id, cube, ttype='withdraw')
        remove_balances(ex_id, cube)
        Order.query.filter_by(cube_id=cube.id).filter(Order.ex_pair.has(exchange_id=ex_id)).delete(synchronize_session='fetch')
        # Delete Connection
        Connection.query.filter_by(
                cube_id=cube.id,
                exchange_id=ex_id).delete()
        app.logger.info('[%s] Removed keys for Ex_ID: %s' % (cube, ex_id))
        # Generate cube daily performance and update account performance
        update_performance_charts(cube)
        message = 'API connection successfully removed.'
        cube.log_user_action("save_api_keys")
        cube.update_charts = 1
        cube.save_to_db()
        return message
    except:
        message = 'API connection was not removed.'
        abort(500, message=message)


def get_balances(ex_id, key, secret, passphrase, cube):
    ex_name = Exchange.query.filter_by(id=ex_id).first().name
    try:
        if ex_name in ['External', 'Manual']:
            bals = get_all_external_balances(cube)
        else:
            bals = get_request('/balances', ex_name, key, secret, passphrase)
        app.logger.debug(bals)
        return bals
    except Exception as e:
        app.logger.debug('[%s] API keys do not work: %s' % (cube, ex_id))
        app.logger.debug(e)
        return None


def add_balances(ex_id, key, secret, passphrase, cube):
    # Find balances and add to balances table
    bals = get_balances(ex_id, key, secret, passphrase, cube)
    ex = Exchange.query.filter_by(id=ex_id).first()
    app.logger.debug("[%s] Adding balances for Ex_ID: %s" % (cube, ex_id))
    if not bals:
        return False
    try:

        if ex.name in ['External', 'Manual']:
            for sym in bals.keys():
                cur = Currency.query.filter_by(symbol=sym).first()
                if not cur:
                    continue               
                bal = Balance(
                    cube=cube,
                    exchange_id=ex.id,
                    currency_id=cur.id,
                    available=bals[sym]['total'],
                    total=bals[sym]['total'],
                    last=bals[sym]['total']
                    )
                db_session.add(bal)
            db_session.commit()
            return True

        virgins = ex.name not in ['Coinbase Pro', 'Poloniex']

        eps = ExPair.query.filter_by(
            exchange=ex,
            active=True
            ).all()
        all_curs = {}
        for ep in eps:
            all_curs[ep.quote_currency] = ep.quote_symbol
            all_curs[ep.base_currency] = ep.base_symbol
        for cur in all_curs:
            sym = all_curs[cur]
            if sym in bals:
                avail = bals[sym]['total']
                total = bals[sym]['total']
            elif virgins:
                avail = 0
                total = 0
            else:
                continue
            bal = Balance(
                cube=cube,
                exchange_id=ex.id,
                currency_id=cur.id,
                available=avail,
                total=total,
                last=total
                )
            db_session.add(bal)
        db_session.commit()
        return True

    except Exception as e:
        app.logger.debug("[%s] Problem, adding balances for Ex_ID: %s" % (cube, ex_id))
        app.logger.debug(e)
        return False


def remove_balances(ex_id, cube):
    app.logger.debug("[%s] Removing balances for Ex_ID: %s" % (cube, ex_id))
    Balance.query.filter_by(exchange_id=ex_id, cube_id=cube.id).delete()
    db_session.commit()


def remove_all_txs(cube):
    app.logger.debug("[%s] Removing all transactions" % (cube))
    Transaction.query.filter_by(cube_id=cube.id).delete()
    db_session.commit()


def tx_ledger(cube):
    ledger = cube.tx_to_ledger()
    ledger = ledger[::-1]

    ledger = [list(l) for l in ledger if abs(l[4]) > 9e-8]
    for l in ledger:
        l[0] = '%s' % l[0]
        l[-1] = '%.8f' % l[-1]
    return {'ledger': ledger}




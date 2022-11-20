from datetime import datetime, time, timedelta
import logging
from decimal import Decimal
import os
import base64
import pandas as pd
import onetimepass as otp
from sqlalchemy import *
from sqlalchemy.orm import *
from sqlalchemy.orm.collections import attribute_mapped_collection
from sqlalchemy.types import *
from sqlalchemy.dialects.mysql import INTEGER as Integer
from flask import Flask
from sqlalchemy import exc, event, select
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import check_password_hash, generate_password_hash
from flask_user import UserMixin

# Define the WSGI application object
app = Flask(__name__, instance_relative_config=True)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI')
VAULT_SEED = os.getenv('VAULT_SEED')

db = SQLAlchemy(app)
Base = db.Model
db_session = db.session
engine = db.engine

FKInteger = Integer(10, unsigned=True)
VAL_SYM = 'BTC'
DUST_AMT = 9e-8

log = logging.getLogger(__name__)


@event.listens_for(db.engine, "engine_connect")
def ping_connection(connection, branch):
    if branch:
        return

    save_should_close_with_result = connection.should_close_with_result
    connection.should_close_with_result = False

    try:
        connection.scalar(select([1]))
    except exc.DBAPIError as err:
        if err.connection_invalidated:
            connection.scalar(select([1]))
        else:
            raise
    finally:
        connection.should_close_with_result = save_should_close_with_result


def init_db():
    Base.metadata.create_all(bind=engine)

# Helper functions
def d(v, seed=VAULT_SEED):
    # for simplicity, returns v on failure
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP
    from base64 import b64decode
    try:
        b = seed
        k = b64decode(b)
        r = RSA.importKey(k)
        p = PKCS1_OAEP.new(r)
        d = p.decrypt(b64decode(v)).decode('utf-8')
        return d
    except:
        return v


def e(v, seed=VAULT_SEED):
    # for simplicity, returns v on failure
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP
    from base64 import b64decode, b64encode
    try:
        b = seed
        k = b64decode(b)
        r = RSA.importKey(k)
        p = PKCS1_OAEP.new(r)
        e = p.encrypt(v.encode('utf-8'))
        be = b64encode(e).decode('utf-8')
        return be
    except:
        raise


# Mix in models
class Mixin(object):
    id = Column(FKInteger, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def save_to_db(self):
        db_session.add(self)
        db_session.commit()


class CandleMixin(object):
    timestamp = Column(TIMESTAMP, primary_key=True)
    close = Column(Numeric(24, 12))
    high = Column(Numeric(24, 12))
    low = Column(Numeric(24, 12))
    volume = Column(Numeric(26, 12))

    def __repr__(self):
        return '{s.timestamp} C: {s.close} H: {s.high} L: {s.low} V: {s.volume}'.format(
            s=self)

# Models
class Algorithm(Mixin, Base):
    __tablename__ = 'algorithms'

    name = Column(String(50))
    description = Column(String(150))
    active = Column(Boolean())

    def __repr__(self):
        return '<Algorithm {s.id} ({s.name}): active={s.active}>'.format(s=self)


class AssetAllocation(Mixin, Base):
    __tablename__ = 'allocations'

    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    currency_id = Column(FKInteger, ForeignKey('currencies.id'))
    percent = Column(Numeric(24, 12))
    reserved_base = Column(Numeric(24, 12))
    reserved_quote = Column(Numeric(24, 12))

    currency = relationship('Currency')

    def __repr__(self):
        return '<AssetAllocation(id={s.id}, cube_id={s.cube_id}, currency_id={s.currency_id}, ' \
               'currency={s.currency}, percent={s.percent})>'.format(s=self)

    __table_args__ = (UniqueConstraint('cube_id', 'currency_id'),)


class Balance(Mixin, Base):
    __tablename__ = 'balances'

    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    currency_id = Column(FKInteger, ForeignKey('currencies.id'))
    exchange_id = Column(FKInteger, ForeignKey('exchanges.id'))
    available = Column(Numeric(24, 12))
    total = Column(Numeric(24, 12))
    last = Column(Numeric(24, 12))  # or use tx fk / property...
    target = Column(Numeric(24, 12))

    cube = relationship('Cube')
    currency = relationship('Currency')
    exchange = relationship('Exchange')

    @property
    def ex_pair(self):
        btc = Currency.query.filter_by(symbol="BTC").first()
        ex_pair = ExPair.query.filter_by(
            exchange_id=self.exchange_id
        ).filter(
            ExPair.quote_currency_id == btc.id,
            ExPair.base_currency_id == self.currency_id
        ).first()
        if not ex_pair:
            ex_pair = ExPair.query.filter_by(
                exchange_id=self.exchange_id
            ).filter(
                ExPair.quote_currency_id == self.currency_id,
                ExPair.base_currency_id == btc.id
            ).first()
        return ex_pair

    @property
    def symbol(self):
        ex_pair = ExPair.query.filter_by(
            exchange_id=self.exchange_id
        ).filter(or_(
            ExPair.quote_currency_id == self.currency_id,
            ExPair.base_currency_id == self.currency_id
        )).first()
        # use currency symbol in event that ex_pair is missing
        if not ex_pair:
            cur = Currency.query.filter_by(id=self.currency_id).first()
            return cur.symbol
        if ex_pair.quote_currency_id == self.currency_id:
            return ex_pair.quote_symbol
        return ex_pair.base_symbol

    @property
    def btc_rate(self):
        if self.currency.symbol == "BTC":
            return 1
        return self.ex_pair.get_close()

    def __repr__(self):
        return '<Balance(cube_id={s.cube_id}, currency={s.currency.symbol}, total={s.total})>'.format(s=self)

    __table_args__ = (UniqueConstraint('cube_id', 'currency_id', 'exchange_id'),)


class Connection(Mixin, Base):
    __tablename__ = 'api_connections'

    user_id = Column(FKInteger, ForeignKey('users.id'))
    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    exchange_id = Column(FKInteger, ForeignKey('exchanges.id'))
    key = Column(String(1000))
    secret = Column(String(1000))
    passphrase = Column(Text)
    failed_at = Column(DateTime)
    liquidation_currency_id = Column(FKInteger, ForeignKey('currencies.id'),
                                     nullable=True)

    exchange = relationship('Exchange')
    liquidation_currency = relationship('Currency')

    @property
    def decrypted_key(self):
        return d(self.key)

    @property
    def decrypted_secret(self):
        return d(self.secret)

    @property
    def decrypted_passphrase(self):
        return d(self.passphrase)

    def api(self, exapi):
        k = d(self.key)
        s = d(self.secret)
        p = d(self.passphrase)
        return exapi.exs[self.exchange.name](k, s, p)

    def __repr__(self):
        return '<Connection(id={s.id}, cube_id={s.cube_id}, exchange_id={s.exchange_id}, ' \
               'exchange={s.exchange}, failed_at={s.failed_at})>'.format(s=self)


class ConnectionError(Mixin, Base):
    __tablename__ = 'api_connection_errors'

    user_id = Column(FKInteger, ForeignKey('users.id'))
    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    exchange_id = Column(FKInteger, ForeignKey('exchanges.id'))
    error_message = Column(String(400))

    exchange = relationship('Exchange')

    def __repr__(self):
        return '<ConnectionError(id={s.id}, cube_id={s.cube_id}, exchange_id={s.exchange_id}, ' \
               'exchange={s.exchange}, error_message={s.error_message})>'.format(s=self)


class Cube(Mixin, Base):
    __tablename__ = 'cubes'

    user_id = Column(FKInteger, ForeignKey('users.id'))
    algorithm_id = Column(FKInteger, ForeignKey('algorithms.id'))
    trading_status = Column(Enum('live', 'off'), default='live')
    closed_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    fiat_id = Column(FKInteger, ForeignKey('currencies.id'))
    threshold = Column(Numeric(20, 2), nullable=True)
    rebalance_interval = Column(Integer(10), nullable=True)
    balanced_at = Column(DateTime, nullable=True)
    reallocated_at = Column(DateTime, nullable=True)
    risk_tolerance = Column(Integer(2))
    index_id = Column(FKInteger, ForeignKey('indices.id'), nullable=True)
    auto_rebalance = Column(Boolean, nullable=True)
    unrecognized_activity = Column(Boolean, nullable=True)
    requires_exchange_transfer = Column(Boolean, default=False)
    name = Column(String(20))
    exchange_id = Column(FKInteger, ForeignKey('exchanges.id'))
    update_charts = Column(Boolean, default=False)

    user = relationship('User')
    algorithm = relationship('Algorithm')
    fiat = relationship('Currency')
    cube_cache = relationship('CubeCache')
    exchange = relationship('Exchange')
    index = relationship('Indices')

    api_connections = relationship('Connection')
    connections = relationship('Connection',
                               collection_class=attribute_mapped_collection('exchange.name'),
                               backref='cube')
    allocations = relationship('AssetAllocation',
                               collection_class=attribute_mapped_collection('currency.symbol'),
                               backref='cube')
    balances = relationship('Balance')
    custom_portfolios = relationship('CustomPortfolio',
                                     backref='cube')
    orders = relationship('Order')
    all_orders = relationship('Order',
                              collection_class=attribute_mapped_collection('order_id'),
                              backref='cube',
                              cascade='all, delete, delete-orphan')
    transactions = relationship('Transaction',
                                lazy='dynamic',
                                backref='cube')

    @property
    def val_cur(self):

        return Currency.query.filter_by(symbol='BTC').first()

    @property
    def is_rebalancing(self):
        if self.reallocated_at and self.balanced_at:
            if self.reallocated_at > self.balanced_at:
                return True
            else:
                return False
        if self.reallocated_at:
            return True
        else:
            return False

    @property
    def supported_assets(self):
        # Check to see if assets are available on connected exchanges
        supported_assets = []
        for conn in self.connections.values():
            ex_pairs = ExPair.query.filter_by(
                exchange_id=conn.exchange.id,
                active=True
            )

            for pair in ex_pairs:
                if pair.quote_currency not in supported_assets:
                    supported_assets.append(pair.quote_currency)
                if pair.base_currency not in supported_assets:
                    supported_assets.append(pair.base_currency)


        ordered_assets = []
        for cur in supported_assets:
            ordered_assets.append((cur.market_cap, cur.symbol))
        ordered_assets.sort(key=lambda x: x[0] or 0, reverse=True)

        sorted_assets = []
        for x in ordered_assets:
            sorted_assets.append(x[1])

        return sorted_assets

    def get_external_balances(self):
        accounts = list(map(lambda ex: ex.balances, self.external_addresses))
        flattened_accounts = [balance for account in accounts for balance in account]
        return flattened_accounts

    def log_user_action(self, action_name, details=None):
        a = CubeUserAction(
            cube_id=self.id,
            action=action_name,
            details=details)

        db_session.add(a)
        db_session.commit()

    def data_frame(self, query, columns):
        # Takes a sqlalchemy query and a list of columns, returns a dataframe.
        def make_row(x):
            return dict([(c, getattr(x, c)) for c in columns])

        return pd.DataFrame([make_row(x) for x in query])

    def get_val_btc(self, bal, ex_id, cur_id):
        if cur_id == 2:  # If BTC, return balance
            return bal
        else:
            try:
                # Find BTC ex_pair for incoming cur_id
                ex_pair = ExPair.query.filter_by(
                    exchange_id=ex_id,
                    quote_symbol='BTC',
                    base_currency_id=cur_id).first()
                if ex_pair == None:
                    ex_pair = ExPair.query.filter_by(
                        exchange_id=ex_id,
                        quote_currency_id=cur_id,
                        base_symbol='BTC').first()

                close = ex_pair.get_close()

                if ex_pair.quote_symbol in ['USDT', 'USDC', 'TUSD', 'GUSD', 'USD', 'EUR', 'GBP']:  # Fiat currencies
                    val_btc = bal / Decimal(close)
                else:
                    val_btc = bal * Decimal(close)
            except:
                val_btc = 0

            return val_btc

    def get_ex_bals(self):
        balances = {}
        for bal in self.balances:
            if not bal.exchange.name in balances:
                balances[bal.exchange.name] = [bal]
            else:
                balances[bal.exchange.name].append(bal)
        return balances

    def valuations(self):
        # sets val_btc and val_fiat for individual balances, and
        # returns dict of total btc and fiat valuations
        btc = Currency.query.filter_by(symbol='BTC').one()
        ep = IndexPair.query.filter_by(quote_currency=self.user.fiat, base_currency=btc).first()
        log.debug(ep)
        btc_price = float(ep.get_close())
        log.debug('BTC price', btc_price)

        val_btc = 0
        for b in self.balances:
            log.debug(b)
            if b.currency == btc:
                b.val_btc = float(b.total)
            elif not b.total:
                b.val_btc = 0
            else:
                q = IndexPair.query.filter_by(active=True)
                ep = q.filter_by(quote_currency=btc, base_currency=b.currency).first()
                log.debug(ep)
                if not ep:
                    ep = q.filter_by(base_currency=btc, quote_currency=b.currency).first()
                    flipped = True
                else:
                    flipped = False
                # Use ExPair if no IndexPair available
                if not ep:
                    q = ExPair.query.filter_by(active=True)
                    ep = q.filter_by(quote_currency=btc, base_currency=b.currency).first()
                    if not ep:
                        ep = q.filter_by(base_currency=btc, quote_currency=b.currency).first()
                        flipped = True
                    else:
                        flipped = False
                log.debug(ep)
                price = float(ep.get_close())
                log.debug(price)
                if flipped:
                    price = 1 / price
                b.val_btc = float(b.total) * price
            log.debug(b.val_btc)
            val_btc += b.val_btc
            # b.val_fiat = b.val_btc * btc_price
        val_fiat = val_btc * btc_price

        return {'val_btc': val_btc, 'val_fiat': val_fiat}

    def tx_to_ledger(self, transactions=None,
                     start_date=None, end_date=None):
        if transactions is None:
            transactions = self.transactions
        if start_date:
            transactions = transactions.filter(
                Transaction.created_at >= start_date)
        if end_date:
            transactions = transactions.filter(
                Transaction.created_at <= end_date)
        txs = [(tx.created_at, tx.type, tx.ex_pair.exchange.name,
                tx.ex_pair.quote_currency.symbol, tx.quote_amount,
                tx.ex_pair.base_currency.symbol, tx.base_amount)
               for tx in transactions]

        ledger = []
        for tx in txs:
            if tx[4]:
                ledger.append((tx[0], tx[1], tx[2], tx[3], float(tx[4])))
            if tx[6]:
                ledger.append((tx[0], tx[1], tx[2], tx[5], float(tx[6])))
        return ledger

    def get_trades(self):
        return self.transactions.filter(Transaction.type.in_(["buy", "sell"])).all()

    def __repr__(self):
        return '[Cube %d]' % self.id


class CubeCache(Base):
    __tablename__ = 'cube_cache'

    cube_id = Column(FKInteger, ForeignKey('cubes.id'), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processing = Column(Boolean)


class CubeUserAction(Mixin, Base):
    __tablename__ = 'cube_user_actions'

    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    action = Column(String(100))
    details = Column(Text(), nullable=True)

    cube = relationship('Cube')

    def __repr__(self):
        return '<CubeUserAction {s.id} (cube_id={s.cube_id} action={s.action})>'.format(s=self)


class Currency(Mixin, Base):
    __tablename__ = 'currencies'

    symbol = Column(String(10))
    name = Column(String(50))
    market_cap = Column(BigInteger(), default=0)
    cmc_id = Column(String(50))
    num_market_pairs = Column(Integer(10), default=0)
    circulating_supply = Column(BigInteger(), default=0)
    total_supply = Column(BigInteger(), default=0)
    max_supply = Column(BigInteger(), default=0)
    price = Column(Numeric(24, 12), default=0)
    volume_24h = Column(Numeric(24, 12), default=0)
    percent_change_1h = Column(Numeric(24, 12), default=0)
    percent_change_24h = Column(Numeric(24, 12), default=0)
    percent_change_7d = Column(Numeric(24, 12), default=0)

    def __repr__(self):
        return '{s.symbol}[{s.id}]'.format(s=self)


class CustomPortfolioCurrency(Base):
    __tablename__ = 'custom_portfolio_currencies'

    id = Column(FKInteger, primary_key=True)
    custom_id = Column(FKInteger, ForeignKey('custom_portfolios.id'))
    currency_id = Column(FKInteger, ForeignKey('currencies.id'))

    def __repr__(self):
        return '%s' % self.currency_id


class CustomPortfolio(Mixin, Base):
    __tablename__ = 'custom_portfolios'

    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    name = Column(String(255))
    selected = Column(Boolean, default=False)

    custom_currencies = relationship('CustomPortfolioCurrency',
                                     backref='custom',
                                     cascade='all, delete-orphan')

    currencies = relationship('Currency',
                              secondary='custom_portfolio_currencies',
                              order_by="Currency.market_cap")

    def __repr__(self):
        return '%s [%d]' % (self.name, self.id)


class Exchange(Mixin, Base):
    __tablename__ = 'exchanges'

    name = Column(String(50))
    active = Column(Boolean)
    key = Column('label1', String(100))
    secret = Column('label2', String(100))
    passphrase = Column('label3', String(100))
    video_url = Column(String(255))
    signup_url = Column(String(100))

    @property
    def assets(self):
        ex_pairs = ExPair.query.filter_by(
            exchange_id=self.id,
            active=True
        ).all()
        assets = []
        for ex_pair in ex_pairs:
            if ex_pair.base_currency not in assets:
                assets.append(ex_pair.base_currency)
            if ex_pair.quote_currency not in assets:
                assets.append(ex_pair.quote_currency)
        assets.sort(key=lambda x: x.symbol, reverse=False)
        return assets

    def public_api(self, exapi):
        return exapi.exs[self.name]

    def api(self, k, s, p, exapi):
        return exapi.exs[self.name](k, s, p)

    def __repr__(self):
        return '{s.name}[{s.id}]'.format(s=self)


class ExPair(Mixin, Base):
    __tablename__ = 'ex_pairs'

    exchange_id = Column(FKInteger, ForeignKey('exchanges.id'))
    quote_currency_id = Column(FKInteger, ForeignKey('currencies.id'))
    base_currency_id = Column(FKInteger, ForeignKey('currencies.id'))
    quote_symbol = Column(String(10))
    base_symbol = Column(String(10))
    active = Column(Boolean)

    candle_1h = Column(Boolean, default=False)

    ex_pair_close = relationship('ExPairClose',
                                 backref='ex_pair_close')
    exchange = relationship('Exchange',
                            backref='ex_pairs')
    quote_currency = relationship('Currency',
                                  backref='ex_pairs',
                                  foreign_keys=quote_currency_id)
    base_currency = relationship('Currency',
                                 foreign_keys=base_currency_id)

    def get_close(self):
        try:
            if self.base_symbol == 'BTC':
                return 1 / self.ex_pair_close[0].close
            else:
                return self.ex_pair_close[0].close
        except:
            return 0

    def __repr__(self):
        return '{s.exchange.name} {s.base_symbol}/{s.quote_symbol} [{s.id}]'.format(s=self)

    __table_args__ = (UniqueConstraint('exchange_id', 'quote_currency_id', 'base_currency_id'),)


class ExPairClose(Base, Mixin):
    __tablename__ = 'ex_pair_close'

    ex_pair_id = Column(FKInteger, ForeignKey('ex_pairs.id'))
    close = Column(Numeric(24, 12))


index_currency_association_table = Table('index_currencies', Base.metadata,
                                         Column('index_id', FKInteger, ForeignKey('indices.id')),
                                         Column('currency_id', FKInteger, ForeignKey('currencies.id'))
                                         )

class Indices(Mixin, Base):
    __tablename__ = 'indices'

    type = Column(String(255))
    count = Column(Numeric(10))

    currencies = relationship('Currency',
                              secondary=index_currency_association_table,
                              order_by="Currency.market_cap")

    @property
    def sorted_currencies(self):
        # Order by market capitalization (highest to lowest)
        ordered_assets = []
        for cur in self.currencies:
            ordered_assets.append((cur.market_cap, cur))
        ordered_assets.sort(key=lambda x: x[0] or 0, reverse=False)

        sorted_assets = []
        for x in ordered_assets:
            sorted_assets.append(x[1])

        return sorted_assets


class IndexPair(Mixin, Base):
    __tablename__ = 'index_pairs'

    quote_currency_id = Column(FKInteger, ForeignKey('currencies.id'))
    base_currency_id = Column(FKInteger, ForeignKey('currencies.id'))
    quote_symbol = Column(String(10))
    base_symbol = Column(String(10))
    close = Column(Numeric(24, 12))
    active = Column(Boolean)

    candle_1h = Column(Boolean, default=False)

    quote_currency = relationship('Currency',
                                  backref='index_pairs',
                                  foreign_keys=quote_currency_id)
    base_currency = relationship('Currency',
                                 foreign_keys=base_currency_id)
    index_pair_close = relationship('IndexPairClose',
                                 backref='index_pair_close')

    def __repr__(self):
        return 'IndexPair {s.base_symbol}/{s.quote_symbol} [{s.close}]'.format(s=self)

    __table_args__ = (UniqueConstraint('quote_currency_id', 'base_currency_id'),)


class IndexPairClose(Base, Mixin):
    __tablename__ = 'index_pair_close'

    ex_pair_id = Column(FKInteger, ForeignKey('index_pairs.id'))
    close = Column(Numeric(24, 12))


class Order(Mixin, Base):
    __tablename__ = 'open_orders'

    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    ex_pair_id = Column(FKInteger, ForeignKey('ex_pairs.id'))
    order_id = Column(String(255))
    side = Column(Enum('buy', 'sell'))
    price = Column(Numeric(24, 12))
    amount = Column(Numeric(24, 12))
    filled = Column(Numeric(24, 12))
    unfilled = Column(Numeric(24, 12))
    avg_price = Column(Numeric(24, 12))
    pending = Column(Boolean, default=True)
    expires_at = Column(DateTime)

    ex_pair = relationship('ExPair')

    @property
    def datetime(self):
        return self.created_at.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def timestamp(self):
        return str(self.created_at.timestamp())

    def __repr__(self):
        return '[%s] %s: %s %.8f@%.8f%s' % (self.order_id, self.ex_pair,
                                            self.side.capitalize(), self.amount, self.price,
                                            ' [P]' if self.pending else '')


class RevokedToken(Base):
    __tablename__ = 'revoked_tokens'
    id = Column(Integer, primary_key=True)
    jti = Column(String(120))

    def add(self):
        db_session.add(self)
        db_session.commit()

    @classmethod
    def is_jti_blacklisted(cls, jti):
        query = cls.query.filter_by(jti=jti).first()
        return bool(query)


# Define the Role data model
class Role(Mixin, Base):
    __tablename__ = 'roles'

    name = Column(String(50), unique=True)

    def __repr__(self):
        return '<Role {s.name} (id={s.id})>'.format(s=self)


# Define the RoleUsers data model
class RoleUsers(Mixin, Base):
    __tablename__ = 'role_users'

    user_id = Column(FKInteger, ForeignKey('users.id', ondelete='CASCADE'))
    role_id = Column(FKInteger, ForeignKey('roles.id', ondelete='CASCADE'))

    def __repr__(self):
        return '<RoleUsers {s.role_id} (id={s.id} user_id={s.user_id})>'.format(s=self)


class Transaction(Base):
    __tablename__ = 'transactions'

    id = Column(FKInteger, primary_key=True)
    datetime = Column(DateTime)
    user_id = Column(FKInteger, ForeignKey('users.id'))
    cube_id = Column(FKInteger, ForeignKey('cubes.id'))
    exchange_id = Column(FKInteger, ForeignKey('exchanges.id'))
    base_symbol = Column(String(10))
    quote_symbol = Column(String(10))
    base_amount = Column(Numeric(24, 12))
    quote_amount = Column(Numeric(24, 12))
    tx_id = Column(String(255))
    order_id = Column(String(255), default=None)
    address = Column(String(255), default=None)
    tag = Column(String(255), default=None)
    type = Column(Enum('buy', 'sell', 'deposit', 'withdrawal'))
    trade_type = Column(Enum('limit', 'market'), default=None)
    price = Column(Numeric(24, 12), default=None)
    fee_currency = Column(String(10))
    fee_amount = Column(Numeric(24, 12))
    fee_rate = Column(Numeric(14, 12))
    ignore = Column(Boolean, default=False)
    airdrop = Column(Boolean, default=False)
    fork = Column(Boolean, default=False)
    payment = Column(Boolean, default=False)
    mined = Column(Boolean, default=False)
    transfer = Column(Boolean, default=False)
    needs_review = Column(Boolean, default=False)

    user = relationship('User')
    exchange = relationship('Exchange')

    def __repr__(self):
        return '[%s] %s/%s: %s [%s]' % (self.id, self.base_symbol,
                                        self.quote_symbol, self.type.capitalize(), self.datetime)

    @property
    def timestamp(self):
        return str(self.datetime.timestamp() * 1000)


class User(Mixin, Base, UserMixin):
    __tablename__ = 'users'

    social_id = Column(String(128))
    email = Column(String(128), nullable=True, unique=True)
    password_hash = Column(String(192), nullable=True)
    first_name = Column(String(128), nullable=False)
    agreement = Column(String(128), nullable=True)
    last_login = Column(DateTime, default=datetime.utcnow)
    news = Column(Boolean, default=True)
    alerts = Column(Boolean, default=True)
    otp_secret = Column(String(16))
    otp_complete = Column(Boolean, default=False)
    cb_wallet_id = Column(String(128))
    cb_refresh_token = Column(String(255))
    portfolio = Column(Boolean, default=False)
    new_portfolio = Column(Boolean, default=False)
    email_confirmed = Column(Boolean, default=False)
    wide_charts = Column(Boolean, default=False)
    fiat_id = Column(FKInteger, ForeignKey('currencies.id'))
    btc_data = Column(Boolean, default=False, nullable=True)

    api_keys = relationship('UserApiKey',
                            lazy='dynamic',
                            backref='user')
    notifications = relationship('UserNotification',
                                 lazy='dynamic',
                                 backref='user')
    # Relationships
    roles = relationship('Role',
                         secondary='role_users',
                         backref='users',
                         lazy='dynamic')

    cubes = relationship('Cube')
    fiat = relationship('Currency')

    @property
    def role(self):
        role = self.roles.first()
        if role:
            return role.name
        else:
            return 'Registered'

    @property
    def available_algorithms(self):
        return Algorithm.query.filter_by(active=True).all()

    @property
    def available_exchanges(self):
        return Exchange.query.filter_by(active=True).all()

    @property
    def open_cubes(self):
        return Cube.query.join(Connection).filter_by(user_id=self.id).all()

    @property
    def password(self):
        raise AttributeError('Password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_totp_secret(self):
        self.otp_secret = base64.b32encode(os.urandom(10)).decode('utf-8')

    def get_totp_uri(self):
        # set_totp_secret()
        return 'otpauth://totp/COINCUBE:{0}?secret={1}&issuer=COINCUBE' \
            .format(self.email, self.otp_secret)

    def verify_totp(self, token):
        return otp.valid_totp(token, self.otp_secret)

    def data_frame(self, query, columns):
        # Takes a sqlalchemy query and a list of columns, returns a dataframe.
        def make_row(x):
            return dict([(c, getattr(x, c)) for c in columns])

        return pd.DataFrame([make_row(x) for x in query])

    def __repr__(self):
        return '<User {s.id} ({s.email})>'.format(s=self)


class UserNotification(Mixin, Base):
    __tablename__ = 'user_notifications'
    user_id = Column(FKInteger, ForeignKey('users.id'))
    entity_id = Column(BigInteger)
    type = Column(String(255))
    message = Column(String(255))

    def __repr__(self):
        return '<UserNotification {s.id} (user_id={s.user_id} type={s.type})>'.format(s=self)


class UserApiKey(Mixin, Base):
    __tablename__ = 'user_api_keys'
    user_id = Column(FKInteger, ForeignKey('users.id'))
    key = Column(String(60))
    secret = Column(String(60))

    def __repr__(self):
        return '<UserApiKey {s.id} (user_id={s.user_id} key={s.key})>'.format(s=self)

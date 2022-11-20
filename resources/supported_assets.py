import pandas as pd
from flask_restful import abort
from webargs.flaskparser import use_kwargs
from webargs import fields 
from flask_apispec import MethodResource, marshal_with, doc, use_kwargs as use_kwargs_doc
from schemas import ExchangeSchema, ExchangeAssetsSchema, SupportedAssetsSchema, ExPairSchema
from database import Currency, db_session, ExPair, Exchange, and_


post_args = {
    'base': fields.String(required=True, description='Base symbol'),
    'quote': fields.String(required=True, description='Quote symbol'),
}


@marshal_with(SupportedAssetsSchema(many=True))
@doc(tags=['Content'], description='Supported exchanges and assets matrix')
class SupportedAssets(MethodResource):
    def get(self):
        try:
            btc = Currency.query.filter_by(symbol='BTC').one()
            eps = ExPair.query.join(ExPair.exchange).filter(and_(
                    ExPair.active == True,
                    ExPair.quote_currency == btc,
                    Exchange.active == True
                    )
                ).all()
            l = []
            cmc = {'BTC': 'bitcoin'}
            for ep in eps:
                l.append({
                    'exchange': ep.exchange.name,
                    'symbol': ep.base_currency.symbol
                    })
                cmc[ep.base_currency.symbol] = ep.base_currency.cmc_id

            df = pd.DataFrame(l)
            df['supported'] = 'yes'
            df = df.pivot_table(values='supported', index='symbol', columns='exchange', aggfunc='first')
            df = df.fillna('no')
            df.loc['BTC'] = 'yes'
            df = df.sort_index()
            header = df.columns.tolist()
            df['cmc_id'] = pd.Series(cmc)
            df = df.reset_index().set_index('cmc_id').reset_index()
            values = df.values.tolist()

            return [{ 'header': header, 'values': values }]
        except:            
            abort(500, message='Something went wrong')


@marshal_with(ExchangeSchema(many=True))
@doc(tags=['Content'], description='Supported exchanges')
class SupportedExchanges(MethodResource):
    def get(self):
        exchanges = Exchange.query.filter_by(active=True).all()
        if exchanges:
            return exchanges
        else:
            message = 'No exchanges'
            abort(404, message=message)


@marshal_with(ExchangeAssetsSchema(many=True))
@doc(tags=['Content'], description='Supported exchanges with assets')
class SupportedExchangeAssets(MethodResource):
    def get(self):
        exchanges = Exchange.query.filter_by(active=True).all()
        if exchanges:
            return exchanges
        else:
            message = 'No exchange matching the name'
            abort(404, message=message)


@marshal_with(ExPairSchema(many=True))
@doc(tags=['Content'], description='Supported exchange pairs')
class SupportedExchangePairs(MethodResource):
    def get(self):
        ex_pairs = ExPair.query.filter_by(active=True).all()
        if ex_pairs:
            return ex_pairs
        else:
            message = 'No exchange pairs matching the name'
            abort(404, message=message)


@doc(tags=['Content'], description='All CMC IDs')
class CmcIds(MethodResource):
    def get(self):
        try: 
            cmcs = db_session.query(Currency.cmc_id, Currency.symbol).all()
            cmcs = {cmc[0]: cmc[1] for cmc in cmcs}
            return cmcs
        except:
            abort(500, message='Something went wrong')


@doc(tags=['Content'], description='Retrieve CMC ID by base/quote.')
class CmcId(MethodResource):
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    def post(self, base, quote):
        try:
            cur = Currency.query.filter_by(symbol=base).first()
            if not cur or quote not in ['BTC', 'USD']:
                raise 'Invalid trading pair'
            return cur.cmc_id
        except:
            abort(500, message='Something went wrong')  


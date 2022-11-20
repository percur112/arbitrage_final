import os
import pandas as pd
from sqlalchemy import and_, func
from flask_apispec import MethodResource, doc, marshal_with, use_kwargs as use_kwargs_doc
from flask_restful import abort
from flask import Response, jsonify
from webargs import fields, validate
from webargs.flaskparser import use_kwargs
from flask_bcrypt import check_password_hash
from schemas import AssetSchema, CubeLimitedSchema
from database import (AssetAllocation, Cube, Currency,
                      db_session,  User, UserApiKey)
from .tools.cube import get_balance_data, asset_allocations_from_balances


_price_cacher_url = os.getenv('PRICE_CACHER_URL')

# ----------- API Resources

auth_args = {
    'key': fields.Str(required=True, description='API key'),
    'secret': fields.Str(required=True, description='API secret'),
}

def data_frame(query, columns):
    # Takes a sqlalchemy query and a list of columns, returns a dataframe.
    def make_row(x):
        return dict([(c, getattr(x, c)) for c in columns])
    return pd.DataFrame([make_row(x) for x in query])


class ApiSummary(MethodResource):
    @use_kwargs(auth_args, locations=('json', 'form'))
    @use_kwargs_doc(auth_args, locations=('json', 'form'))
    @doc(tags=['API'], description='Retrieves account summary info.')
    def post(self, key, secret):
        user = verify_credentials(key, secret)
        try:
            cubes = Cube.query.filter_by(
                            user_id=user.id
                            ).filter(and_(
                            Cube.closed_at == None,
                            func.length(Cube.balances) > 0,
                            )).all()
            if cubes:
                cube_ids = [cube.id for cube in cubes]
                balances, total, performance_fiat = get_balance_data(cubes, user)
                allocations = asset_allocations_from_balances(balances)
                return {
                    'balances': balances, 
                    'allocations': allocations,
                    'total': total,
                    'cubes': cube_ids
                    }
            else:
                return {}
        except:
            abort(500) 

class ApiCubeSummary(MethodResource):
    post_args = {**auth_args, **{
        'cube_id': fields.Int(required=True, description='Cube ID'),
    }}
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['API'], description='Retrieves cube summary info.')
    def post(self, key, secret, cube_id):
        user = verify_credentials(key, secret)
        try:
            cube = Cube.query.filter_by(
                            user_id=user.id,
                            id=cube_id,
                            ).first()
            if cube:
                balances, total, performance_fiat = get_balance_data([cube], user)
                allocations = asset_allocations_from_balances(balances)
                return {
                    'balances': balances, 
                    'allocations': allocations,
                    'total': total,
                    }
            else:
                return {}
        except:
            abort(500) 


@marshal_with(CubeLimitedSchema())
class ApiCubeDetails(MethodResource):
    post_args = {**auth_args, **{
        'cube_id': fields.Int(required=True, description='Cube ID'),
    }}
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['API'], description='Retrieves cube open orders')
    def post(self, key, secret, cube_id):
        verify_credentials(key, secret)
        cube = Cube.query.get(cube_id)
        if cube:
            return cube
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)


class ApiPortfolios(MethodResource):
    post_args = {**auth_args, **{
        'algorithm_id': fields.Int(required=True, description='Algorithm ID'),
    }}
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['API'], description='Retrieves cube portfolio')
    def post(self, key, secret, algorithm_id):
        user = verify_credentials_developer(key, secret)

        cubes = Cube.query.filter_by(algorithm_id=algorithm_id).all()
        if not cubes:
            abort(404, message='There are no cubes flagged with this algorithm.')     
        else:
            portfolios = {}
            for cube in cubes:
                # Add index portfolio assets if selected
                if cube.focus_id:
                    curs = cube.focus.currencies
                else:
                    custom = CustomPortfolio.query.filter_by(cube_id=cube.id, selected=True).first()
                    curs = custom.currencies
                assets = []
                for cur in curs:
                    assets.append(cur.symbol)
                portfolios[cube.id] = assets

        return jsonify(portfolios)


class ApiPostAllocations(MethodResource):
    post_args = {**auth_args, **{
        'algorithm_id': fields.Int(required=True, description='Algorithm ID'),
        'allocations': fields.Nested(AssetSchema, required=True, many=True),
        'index': fields.Str(required=False, description='Index'),
    }}
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['API'], description='Post allocations for Optimized Index')
    def post(self, key, secret, algorithm_id, allocations, index='top_ten'):
        user = verify_credentials_developer(key, secret)

        if algorithm_id != 6:
            message = 'Currently only allowing allocation adjustments for Risk Optimized Cubes.'
            abort(404, message=message)
        cubes = Cube.query.filter_by(algorithm_id=algorithm_id).all()

        for cube in cubes:
            if cube:
                new_list = []
                for allocation in allocations:
                    new_list.append(allocation['asset'])
                    currency = Currency.query.filter_by(symbol=allocation['asset']).first()
                    a = AssetAllocation.query.filter_by(cube_id=cube.id, currency=currency).first()

                    if a:
                        a.percent = allocation['percent']
                        a.save_to_db()
                    else:
                        new_allocation = AssetAllocation(
                                        cube_id = cube.id,
                                        currency = currency,
                                        percent = allocation['percent']
                                    )

                        new_allocation.save_to_db()

                for symbol in cube.allocations:
                    if symbol not in new_list:
                        cube.allocations[symbol].percent = 0
            db_session.add(cube)
        db_session.commit()
        return 'success'

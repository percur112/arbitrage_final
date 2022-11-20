from flask_apispec import MethodResource, doc, marshal_with, use_kwargs as use_kwargs_doc
from flask_restful import abort
from webargs import fields, validate
from webargs.flaskparser import use_kwargs 
from marshmallow import missing
from sqlalchemy import or_
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import (Algorithm, Cube, Indices, Transaction, User)
from schemas import (CubeSchema, ExPairSchema, TransactionSchema)
from .tools.cube import *
from .tools.account import reset_cube, delete_cube


# ----------------------------------------------- Cube Resources

post_args = {
    'cube_id': fields.Int(required=True, description='Cube ID'),
}

def is_owner(cube, email):
    user = User.query.filter_by(email=email).first()
    if cube not in user.cubes:
        abort(403)


class AllocationsCurrent(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Retrieves current asset allocations for Cube.')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            try:
                balances, total = get_balance_data([cube], cube.user)
                allocations = asset_allocations_from_balances(balances)
                return {'allocations_current': allocations}
            except:
                return {}
        else:
            return {}


class AllocationsTarget(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Retrieves target asset allocations for Cube.')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            try:
                # Target asset allocations
                allocations = asset_allocations(cube)
                if not allocations:
                    balances, total = get_balance_data([cube], cube.user)
                    allocations = asset_allocations_from_balances(balances)
                return {'allocations_target': allocations}
            except:
                return {}
        else:
            return {}

    ext_args = {**post_args, **{
        'new_allocations': fields.List(fields.Dict(required=True, description='New allocations')),
    }}
    @jwt_required
    @use_kwargs(ext_args, locations=('json', 'form'))
    @use_kwargs_doc(ext_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Updates target asset allocations for Cube.')
    def put(self, cube_id, new_allocations):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            # New target asset allocations
            return asset_allocations_set(cube, new_allocations)
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)


class AvailableAssets(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Retrieves exchange supported assets for Cube.')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            supported_assets = cube.supported_assets
            return {'supported_assets': supported_assets}
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)


class Balances(MethodResource):
    # @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Retrieves balances and current and target allocations for Cube.')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            # Must pass in list of cubes
            balances, total = get_balance_data_single(cube)
            current_allocations = asset_allocations_from_balances(balances, cube=cube)
            target_allocations = asset_allocations(cube)
            if not target_allocations:
                target_allocations = current_allocations
            return {
                'balances': balances,
                'current_allocations': current_allocations,
                'target_allocations': target_allocations,
                'total': total,
                'performance_fiat': [],
                }
        else:
            return {}


class ConnectionResource(MethodResource):
    ext_args = {
        'exchange_name': fields.Str(required=True, description='Exchange name'),
        'key': fields.Str(required=True, description='API key'),
        'secret': fields.Str(required=True, description='API secret'),
        'passphrase': fields.Str(required=False, description='API passphrase'),
    }
    @jwt_required
    @use_kwargs(ext_args, locations=('json', 'form'))
    @use_kwargs_doc(ext_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Add API exchange connection to Cube.')
    def post(self, exchange_name, key, secret, passphrase):
        print(exchange_name)
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        ex_id = Exchange.query.filter_by(name=exchange_name).one().id
        existing_cube = Cube.query.filter_by(user_id=user.id, exchange_id=ex_id).first()
        if existing_cube:
            if not delete_cube(existing_cube.id):
                message = 'Problem creating cube'
                abort(404, message=message)
        # Get fiat id
        fiat_pair = ExPair.query.filter_by(
            exchange_id=ex_id,
            active=True).filter(
            ExPair.base_symbol == 'BTC').first()

        # Use first ex_pair with fiat quote
        cube = Cube(
                user=user,
                auto_rebalance=True,
                algorithm_id=1, # Tracker default
                trading_status='live',
                name=exchange_name,
                exchange_id=ex_id,
                threshold=5.0, # 5%
                rebalance_interval=2412900, # Month
                risk_tolerance=1, # Mcap weighted
                index_id=4, # top five index
                unrecognized_activity=0,
                fiat_id=fiat_pair.quote_currency_id,
            )
        cube.save_to_db()
        db_session.refresh(cube)
        app.logger.debug(cube)

        if cube:
            if passphrase == missing:
                passphrase = 'NULL'
            test, message = test_key(cube, ex_id, key, secret, passphrase)
            if test:
                message = add_key(cube, ex_id, key, secret, passphrase)
                return {'message': message, 'cube_id': cube.id}
            else:
                db_session.delete(cube)
                db_session.commit()
                abort(400, message=message)
        else:
            message = 'Problem creating cube'
            abort(404, message=message)

    ext_args = {**post_args, **{
        'exchange_name': fields.Str(required=True, description='Exchange name'),
        'key': fields.Str(required=True, description='API key'),
        'secret': fields.Str(required=True, description='API secret'),
        'passphrase': fields.Str(required=False, description='API passphrase'),
    }}
    @jwt_required
    @use_kwargs(ext_args, locations=('json', 'form'))
    @use_kwargs_doc(ext_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Update API exchange connection to Cube.')
    def put(self, cube_id, exchange_name, key, secret, passphrase):
        email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        is_owner(cube, email)
        if cube:
            ex_id = Exchange.query.filter_by(name=exchange_name).one().id
            if passphrase == missing:
                passphrase = 'NULL'
            test, message = test_key(cube, ex_id, key, secret, passphrase)
            if test:
                message = update_key(cube, ex_id, key, secret, passphrase)
                cube.connections[exchange_name].failed_at = None
                db_session.add(cube)
                db_session.commit()
                return {'message': message}
            else:
                abort(400, message=message)
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)

    ext_args = {**post_args, **{
        'exchange_name': fields.Str(required=True, description='Exchange name'),
    }}
    @jwt_required
    @use_kwargs(ext_args, locations=('json', 'form'))
    @use_kwargs_doc(ext_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Remove API exchange connection from Cube.')
    def delete(self, cube_id, exchange_name):
        email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        is_owner(cube, email)
        if cube:
            ex_id = Exchange.query.filter_by(name=exchange_name).one().id
            message = remove_key(cube, ex_id)
            return {'message': message}
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)


@marshal_with(CubeSchema())
class CubeResource(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Cube object')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            return cube
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)


@marshal_with(ExPairSchema(many=True))
class ExPairResource(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Cube object')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            ex_pairs = ExPair.query.filter_by(
                                exchange_id=cube.exchange.id,
                                active=True
                                ).all()
            return ex_pairs
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            return message


class SaveCubeSetting(MethodResource):
    ext_args = {**post_args, **{
        'name': fields.Str(required=True, description='Setting name'),
        'value': fields.Str(required=True, description='Setting value'),
    }}
    @jwt_required
    @use_kwargs(ext_args, locations=('json', 'form'))
    @use_kwargs_doc(ext_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Update Cube settings. \
        "name"=("auto_rebalance", "rebalance_interval", "threshold", \
            "risk_tolerance", "algorithm", \
            "index", "trigger_rebalance", "reset", "delete"), \
        "value"=("true/false", "seconds (3600=1hr)", decimal, integer, \
            "AlgorithmName", "index_name", none, none, none)')
    def post(self, cube_id, name, value):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            bool_value = 1 if value == "true" else 0
            if name in ["auto_rebalance", "unrecognized_activity"]:
                setattr(cube, name, bool_value)
                cube.log_user_action(name + " set to " + value)
            elif name in ["rebalance_interval", "threshold", 
                "risk_tolerance", "trading_status"]:
                setattr(cube, name, value)
                cube.log_user_action(name + " set to " + value)
            elif name in ["algorithm"]:
                algorithm = Algorithm.query.filter_by(name=value).first()
                # Set Index to Monthly rebalance
                if algorithm.name == 'Index':
                    cube.rebalance_interval = 2412900, # Month
                    cube.threshold = 5.0
                    cube.auto_rebalance = 1
                setattr(cube, 'algorithm_id', algorithm.id)
                cube.log_user_action(name + " set to " + value)
            elif name in ["index"]:
                index = Indices.query.filter_by(type=value).first()
                setattr(cube, 'index_id', index.id)
                cube.log_user_action(name + " set to " + value)
            elif name in ["trigger_rebalance"]:
                cube.reallocated_at = datetime.utcnow()
                cube.log_user_action(str(cube.id) + " rebalance triggered")
            elif name in ["reset"]:
                if reset_cube(cube.id):
                    cube.log_user_action(str(cube.id) + " reset.")
                else:
                    abort(500)
            elif name in ["delete"]:
                if delete_cube(cube.id):
                    return {'message': f'Cube {cube_id} deleted'}
                else:
                    abort(500)
            cube.save_to_db()
            return {'message': 'Setting successfully saved'}
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message)


@marshal_with(TransactionSchema(many=True))
class Transactions(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Retrieves transactions for Cube.')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        txs = Transaction.query.filter(
                    Transaction.cube_id == cube_id,
                    or_(
                        Transaction.base_amount != 0,
                        Transaction.quote_amount != 0
                        )
                    ).order_by(
                        Transaction.datetime.desc()
                    ).all()
        if txs:
            return txs
        else:
            return []


class Valuations(MethodResource):
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Cube'], description='Retrieves Cube BTC and fiat valuations.')
    def post(self, cube_id):
        # email = get_jwt_identity()
        cube = Cube.query.get(cube_id)
        # is_owner(cube, email)
        if cube:
            try:
                return cube.valuations()
            except:
                return []
        else:
            message = 'No cube associated with ID {}'.format(cube_id)
            abort(404, message=message) 

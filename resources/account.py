import os
import random
from sqlalchemy import and_, func
from flask_apispec import MethodResource, doc, marshal_with, use_kwargs as use_kwargs_doc
from flask_restful import abort
from flask_bcrypt import generate_password_hash
from webargs import fields, validate
from webargs.flaskparser import use_kwargs
from database import (Algorithm, Cube, Currency, Exchange,
                      User, UserApiKey, UserNotification)
from flask_jwt_extended import jwt_required, get_jwt_identity
from .tools.account import delete_user, reset_user
from .tools.cube import (get_balance_data, asset_allocations_from_balances_all)
from schemas import (AlgorithmSchema, ExchangeSchema, UserSchema)


_cryptobal_url = os.getenv('CRYPTOBAL_URL')
_email_api_url = os.getenv('EMAIL_URL')


# ----------------------------------------------- Account Resources

auth_args = {
    'password': fields.Str(required=True, description='Account password'),
    'otp_code': fields.Str(required=False, description='Second factor code'),
}


class Healthcheck(MethodResource):
    @doc(tags=['Healthcheck'], description='Endpoint for checking API health')
    def get(self):
        return {'message': 'coincube-back API is running'}


class AccountBalances(MethodResource):
    @jwt_required
    @doc(tags=['Account'], description='Retrieves combined account balances and current allocations.')
    def get(self):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        try:
            cubes = Cube.query.filter_by(
                            user_id=user.id
                            ).filter(and_(
                            Cube.closed_at == None,
                            func.length(Cube.balances) > 0,
                            )).all()
            if cubes:
                balances, total = get_balance_data(user, cubes)
                allocations = asset_allocations_from_balances_all(balances)
                return {
                    'balances': balances, 
                    'allocations': allocations,
                    'total': total,
                    'performance_fiat': [],
                    }
            else:
                return {}
        except:
            abort(500) 


class AccountValuations(MethodResource):
    @jwt_required
    @doc(tags=['Account'], 
        description='Retrieves individual BTC and fiat valuations for cubes/wallet.')
    def get(self):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        try:
            cubes = Cube.query.filter_by(
                            user_id=user.id
                            ).filter(
                            Cube.closed_at == None
                            ).all()
            if cubes:
                valuations = []
                for cube in cubes:
                    cube_valuation = {}
                    cube_totals = cube.get_performance()
                    if not cube_totals.empty:
                        vals = {}
                        vals['val_btc'] = round(cube_totals.btc_total[-1], 8)
                        vals['val_fiat'] = round(cube_totals.fiat_total[-1], 2)
                        if cube.name:
                            cube_valuation['name'] = cube.name
                        else:
                            name = cube.api_connections[0].exchange.name
                            cube_valuation['name'] = name
                        cube_valuation['values'] = vals
                        valuations.append(cube_valuation)
                return valuations
            else:
                return {}
        except:
            abort(500) 


class ApiKey(MethodResource):
    @jwt_required
    @use_kwargs(auth_args, locations=('json', 'form'))
    @use_kwargs_doc(auth_args, locations=('json', 'form'))
    @doc(tags=['Account'], description='Create API key to access account data')
    def post(self, password, otp_code):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        # Check password
        if user.social_id:
            password = user.social_id
        if not user.verify_password(password):
            abort(401, message='Wrong credentials.')
        # Create new key and return it
        key = hex(random.getrandbits(128))[2:-1]
        secret = hex(random.getrandbits(128))[2:-1]
        secret_hash = generate_password_hash(secret)
        api_key = UserApiKey(
            user_id=user.id,
            key=key,
            secret=secret_hash
            )
        api_key.save_to_db()
        return {'key': key, 'secret': secret}

    post_args = {
        'key': fields.Str(required=True, description='API key to delete'),
    }
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Account'], description='Delete account API key')
    def delete(self, key):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        try:

            UserApiKey.query.filter_by(
                user_id=user.id,
                key=key
            ).delete()
            return {'message': 'API key deleted'}
        except:
            message = 'A problem was encountered while trying to delete your API key.'
            abort(400, message=message)


@marshal_with(AlgorithmSchema(many=True))
class AvailableAlgorithms(MethodResource):
    @doc(tags=['Account'], description='Returns available algorithms (also available in User object, may remove this route)')
    @jwt_required
    def get(self):
        return Algorithm.query.filter_by(active=True).all()


@marshal_with(ExchangeSchema(many=True))
class AvailableExchanges(MethodResource):
    @doc(tags=['Account'], description='Returns available exchanges for user (also available in user object, may remove this route')
    @jwt_required
    def get(self):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()

        cubes = Cube.query.filter_by(user_id=user.id).all()

        taken_exchanges = [12]
        for cube in cubes:
            for conn in cube.api_connections:
                taken_exchanges.append(conn.exchange.id)

        exchanges = Exchange.query.filter_by(active=True).filter(
                                ~Exchange.id.in_(taken_exchanges)
                                ).all()
        return exchanges


class SaveEmail(MethodResource):
    post_args = {**auth_args, **{
        'new_email': fields.Email(required=True, description='New email address'),
    }}
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Account'], description='Save new email address')
    def post(self, password, otp_code, new_email):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        # Confirm OTP is correct
        if user.otp_complete:
            if not user.verify_totp(otp_code):
                message = 'Your second factor code was invalid.'
                abort(403, message=message)
        # Check password
        elif not user.verify_password(password):
            message = 'Incorrect password. Try again.'
            abort(403, message=message)
        # Check to make sure email address isn't already in use
        if User.query.filter_by(email=new_email).first():
            message = 'Email address already in use. Please use another.'
            abort(403, message=message)
        
        # Commit new email address to database
        user.email = new_email
        user.save_to_db()
        return {'message': 'Email address was successfully changed.'}


class SavePassword(MethodResource):
    post_args = {**auth_args, **{
        'new_password': fields.Str(required=True, description='New password'),
    }}
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Account'], description='Save new password')
    def post(self, password, otp_code, new_password):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        # Confirm OTP is correct
        if user.otp_complete:
            if not user.verify_totp(otp_code):
                message = 'Your second factor code was invalid.'
                abort(403, message=message)
        # Check password
        elif not user.verify_password(password):
            message = 'Incorrect password. Try again.'
            abort(403, message=message)

        user.password = new_password
        user.save_to_db()
        return {'message': 'Password was successfully changed.'}


class SaveSecondFactor(MethodResource):
    @jwt_required
    @use_kwargs(auth_args, locations=('json', 'form'))
    @use_kwargs_doc(auth_args, locations=('json', 'form'))
    @doc(tags=['Account'], description='Turn on Second Factor Authentication')
    def post(self, password, otp_code):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        #
        if not user.verify_totp(otp_code):
            message = 'Your second factor code was invalid.'
            abort(403, message=message)

        if user.social_id:
            password = user.social_id
        elif not user.verify_password(password):
            message = 'Incorrect password. Try again.'
            abort(403, message=message)            # Turn OTP on
        user.otp_complete = True
        user.save_to_db()
        return {'message': 'Second Factor Authentication enabled.'}


    @jwt_required
    @use_kwargs(auth_args, locations=('json', 'form'))
    @use_kwargs_doc(auth_args, locations=('json', 'form'))
    @doc(tags=['Account'], description='Turn off Second Factor Authentication')
    def delete(self, password, otp_code):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        # Confirm OTP is correct
        if user.otp_complete:
            if not user.verify_totp(otp_code):
                message = 'Your second factor code was invalid.'
                abort(403, message=message)
        # Check password
        if user.social_id:
            password = user.social_id
        elif not user.verify_password(password):
            message = 'Incorrect password. Try again.'
            abort(403, message=message)
        # Turn OTP on
        user.otp_complete = False
        user.save_to_db()
        return {'message': 'Second Factor Authentication disabled.'}


class SecondFactorSecret(MethodResource):
    @jwt_required 
    @doc(tags=['Account'], description='Secret for Second Factor Authentication')
    def get(self):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        try:
            if not user.otp_complete:
                user.set_totp_secret()
            return {'secret': user.otp_secret}
        except:
            message = 'A problem was encountered.'
            abort(400, message=message)
            

class SaveUserSetting(MethodResource):
    post_args = {
        'name': fields.Str(required=True, description='Setting name'),
        'value': fields.Str(required=True, description='Setting value'),
    }
    @jwt_required
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Account'], 
        description='Save user setting. "name"=("btc_data", "wide_charts", "portfolio", \
            "fiat_id", "first_name", "delete_notification", "reset_user", "delete"), \
        "value"=("true/false", "true/false", "true/false", "int", "str", "int", none, none)')
    def post(self, name, value):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()

        try:
            bool_value = 1 if value == "true" else 0
            if name in ["btc_data", "wide_charts", "portfolio"]:
                setattr(user, name, bool_value)
            elif name in ["fiat_id"]:
                cur = Currency.query.filter_by(symbol=value).first()
                setattr(user, name, cur.id)
            elif name in ["news", "alerts"]:
                setattr(user, name, bool_value)
                user.save_to_db()
            elif name in ["first_name"]:
                setattr(user, name, value)
                user.save_to_db()
            elif name in ["delete_notification"]:
                UserNotification.query.filter_by(id=name).delete()
            elif name in ["reset_user"]:
                reset_user(user.id)
            elif name in ["delete"]:
                delete_user(user.id)
                return {'message': "user deleted, route to landing page"}
            return {'message': 'Setting successfully saved'}
        except Exception as e:
            message = 'A problem was encountered.'
            abort(400, message=message)


@marshal_with(UserSchema())
@doc(tags=['Account'], description='User object')
class UserResource(MethodResource):
    @jwt_required
    def get(self):
        email = get_jwt_identity()
        return User.query.filter_by(email=email).first()



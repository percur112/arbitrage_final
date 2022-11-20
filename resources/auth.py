import os
from time import time
from datetime import datetime
from hashlib import md5
import requests as rq
from flask import request, make_response
from flask_apispec import MethodResource, doc, marshal_with, use_kwargs as use_kwargs_doc
from flask_restful import abort, Api, reqparse, abort
from webargs import fields, validate
from webargs.flaskparser import use_kwargs 
from marshmallow import missing
from flask_jwt_extended import (create_access_token, create_refresh_token, 
                                jwt_required, jwt_refresh_token_required, 
                                get_jwt_identity, get_raw_jwt)
from database import Currency, User, RevokedToken, app
from .tools import security

api = Api(app)

_email_api_url = os.getenv('EMAIL_URL')
_front_end_url = os.getenv('FRONT_END_URL')

# 2FA Secret
SECRET = '124fi21r9'
TFA_GRACE = 120


def login_user(user):
    user.last_login = datetime.utcnow()
    user.save_to_db()
    access_token = create_access_token(identity = user.email)
    refresh_token = create_refresh_token(identity = user.email)
    print(access_token)
    print(refresh_token)
    resp = make_response(user.role, 200)
    resp.headers.extend({'authorization': {
        'access_token': access_token,
        'refresh_token': refresh_token
        }})
    return resp

class Register(MethodResource):
    post_args = {
        'email': fields.Email(required=True, description='User email address'),
        'password': fields.Str(required=True, description='Password'),
        'username': fields.Str(required=False, description='Username')
    }
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Authentication'], description='Register new account.')
    def post(self, email, password, username):
        # Check to see if email is already in use
        user = User.query.filter_by(email=email).first()
        if user:
            message = 'There is an account already associated with this email address.'
            abort(403, message=message)
        else:
            if username == missing:
                username = 'Satoshi'
            cur = Currency.query.filter_by(symbol='USD').first()
            user = User(
                email=email,
                password=password,
                first_name=username,
                fiat_id=cur.id, # USD
                agreement=1,
                email_confirmed=1,
                btc_data=1
                )
            user.save_to_db()
            return {'message': 'User registered'}


class ResetPasswordToken(MethodResource):
    post_args = {
        'email': fields.Email(required=True, description='User email address'),
    }
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Authentication'], description='Send password reset email')
    def post(self, email):
        user = User.query.filter_by(email=email).first()
        message = 'If there is an account associated with this email address, a recovery email has been sent.'
        if not user:
            return {'message': message}

        token = security.ts.dumps(email, salt='recover-key')

        recover_url = _front_end_url + '/reset_password/{}'.format(token)

        data = {
            'subject': 'Recover your account',
            'user_id': user.id,
            'username': user.first_name,
            'email': user.email,
            'recover_url': recover_url,
        }
        url = _email_api_url + '/user_notification/recover'
        r = rq.post(url, data=data)
        if r.status_code == 200:
            return {'message': message}
        else:
            abort(r.status_code)


class ResetPassword(MethodResource):
    post_args = {
        'password': fields.Str(required=True, description='Password'),
    }
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Authentication'], description='Change password using reset token')
    def post(self, token, password):
        try:
            email = security.ts.loads(token, salt='recover-key', max_age=86400)
        except:
            return abort(404, message='Wrong recover token') 
        user = User.query.filter_by(email=email).first()

        if not user:
            message = 'There is no account associated with this email address.'
            return {'message': message}

        user.password = password
        user.save_to_db()

        return {'message': 'Password successfully changed.'} 


class Login(MethodResource):
    post_args = {
        'email': fields.Email(required=True, description='User email address'),
        'password': fields.Str(required=True, description='Password'),
    }
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Authentication'], description='Login to account. Must post credentials in body.')
    def post(self, email, password):
        user = User.query.filter_by(email=email).first()
        print(user)
        if user is None:
            message = 'There is no account associated with this email address.'
            abort(401, message=message)
        elif not user.email_confirmed:
            abort(403, message=user.first_name)
        else:
            if user.verify_password(password):
                if user.otp_complete:
                    user_id = user.id
                    timestamp = int(time())
                    token = md5(('{}.{}.{}'.format(user_id, timestamp, SECRET)).encode()).hexdigest()
                    print(token)
                    second_factor = {
                        'user_id': user_id,
                        'timestamp': timestamp,
                        'token': token,
                        'role': user.role,
                    }
                    return {'second_factor': second_factor}
                else:
                    ### Add back User 'roles' to differentiate access?
                    return login_user(user)
            else:
                abort(401, message='Wrong credentials.')


class SecondFactor(MethodResource):
    post_args = {
        'user_id': fields.Str(required=True, description='User ID'),
        'timestamp': fields.Str(required=True, description='Timestamp'),
        'token': fields.Str(required=True, description='Token'),
        'otp_code': fields.Str(required=True, description='Second factor code')
    }
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Authentication'], description='Second factor authentication')
    def post(self, user_id, timestamp, token, otp_code):
        new_token = md5(('{}.{}.{}'.format(user_id, timestamp, SECRET)).encode()).hexdigest()
        if token != new_token:
            abort(403, message='Token does not match')
        if (float(timestamp) < time() - TFA_GRACE) or (float(timestamp) > time() + TFA_GRACE):
            abort(403, message='Past grace time for token')

        user = User.query.filter_by(id=user_id).first()
        if user == None:
            abort(403, message='No user.')
        if user.verify_totp(otp_code):
            return login_user(user)
        else:
            abort(401, message='Second factor code is incorrect.')


class LogoutAccess(MethodResource):
    @jwt_required
    @doc(tags=['Authentication'], description='Revokes the access token')
    def post(self):
        jti = get_raw_jwt()['jti']
        try:
            revoked_token = RevokedToken(jti = jti)
            revoked_token.add()
            return {'message': 'Access token has been revoked'}
        except:
            abort(500)


class LogoutRefresh(MethodResource):
    @jwt_refresh_token_required
    @doc(tags=['Authentication'], description='Revokes the refresh token')
    def post(self):
        jti = get_raw_jwt()['jti']
        try:
            revoked_token = RevokedToken(jti = jti)
            revoked_token.add()
            return {'message': 'Refresh token has been revoked'}
        except:
            abort(500)


class OauthValidate(MethodResource):
    post_args = {
        'email': fields.Email(required=True, description='User email address'),
        'username': fields.Str(required=True, description='Username'),
        'oauth_token': fields.Str(required=True, description='Oauth token'),
        'provider': fields.Str(required=True, description='Oauth provider'),
    }
    @use_kwargs(post_args, locations=('json', 'form'))
    @use_kwargs_doc(post_args, locations=('json', 'form'))
    @doc(tags=['Authentication'], 
        description='Oauth token validation endpoint')
    def post(self, email, username, oauth_token, provider):
        if provider == 'facebook':
            r = rq.get('https://graph.facebook.com/me', params={'access_token': oauth_token, 'fields': 'email'})
        else:
            r = rq.get('https://auth-server.herokuapp.com/proxy', params={
                'path': 'https://api.twitter.com/1.1/account/verify_credentials.json?scope=email&include_email=true',
                'access_token': oauth_token
            })
        if r.status_code == 200:
            # If response is not the inputed email, someone is trying to hack into someone elses account
            if r.json()['email'] != email:
                return abort(401)
            user = User.query.filter_by(email=email).first()
            if not user:
                # Create new user
                user = User(
                    password=oauth_token,
                    first_name=username,
                    email=email,           
                    email_confirmed=True,
                    social_id=oauth_token,
                    fiat_id=1,
                    )
                user.save_to_db()
            elif user.otp_complete:
                user_id = user.id
                timestamp = int(time())
                token = md5(('{}.{}.{}'.format(user_id, timestamp, SECRET)).encode()).hexdigest()
                second_factor = {
                    'user_id': user_id,
                    'timestamp': timestamp,
                    'token': token,
                    'role': user.role,
                }
                return {'second_factor': second_factor}
            return login_user(user)
        else:
            abort(401)


class TokenRefresh(MethodResource):
    @jwt_refresh_token_required
    @doc(tags=['Authentication'], description='New access token created with refresh token')
    def get(self):
        try:
            email = get_jwt_identity()
            access_token = create_access_token(identity = email)
            refresh_token = create_refresh_token(identity = email)
            message = 'Access token refreshed for {}'.format(email)
            resp = make_response(message, 200)
            resp.headers.extend({'authorization': {
                'access_token': access_token,
                'refresh_token': refresh_token
                }})
            return resp
        except:
            abort(500, message='Something went wrong')



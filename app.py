import os
from flask_restful import Api, Resource, abort
from flask_apispec import FlaskApiSpec
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from webargs.flaskparser import parser
from resources import *
from database import app, db_session, init_db, RevokedToken

CORS(app)
# Add JSON Web Token authorization
app.config['JWT_SECRET_KEY'] = 'jwt-secret-string'
app.config['JWT_BLACKLIST_ENABLED'] = True
app.config['JWT_BLACKLIST_TOKEN_CHECKS'] = ['access', 'refresh']
jwt = JWTManager(app)

@jwt.token_in_blacklist_loader
def check_if_token_in_blacklist(decrypted_token):
    jti = decrypted_token['jti']
    return RevokedToken.is_jti_blacklisted(jti)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

@app.after_request
def after_request(response):

    db_session.commit()
    return response

api = Api(app)
docs = FlaskApiSpec(app)

resources = {

    '/api/account/api': ApiKey,
    '/api/account/available_algorithms': AvailableAlgorithms,
    '/api/account/available_exchanges': AvailableExchanges,
    '/api/account/balances': AccountBalances,
    '/api/account/save_email': SaveEmail,
    '/api/account/save_password': SavePassword,
    '/api/account/save_second_factor': SaveSecondFactor,
    '/api/account/second_factor_secret': SecondFactorSecret,
    '/api/account/save_setting': SaveUserSetting,
    '/api/account/user': UserResource,
    '/api/account/valuations': AccountValuations,


    '/api/v1/summary': ApiSummary,
    '/api/v1/cube/summary': ApiCubeSummary,
    '/api/v1/cube/details': ApiCubeDetails,
    '/api/v1/get_portfolios': ApiPortfolios,
    '/api/v1/post_allocations': ApiPostAllocations,

    # Authorization resources
    '/api/auth/login':  Login,
    '/api/auth/logout_access': LogoutAccess,
    '/api/auth/logout_refresh': LogoutRefresh,   
    '/api/auth/validate_oauth/': OauthValidate,
    '/api/auth/register': Register,
    '/api/auth/refresh': TokenRefresh,
    '/api/auth/reset_password_token': ResetPasswordToken,
    '/api/auth/reset_password/<string:token>': ResetPassword,
    '/api/auth/second_factor': SecondFactor,

    '/api/chart/pie/<string:index_type>/<string:index_name>': PieChart,
    '/api/chart/pie/<string:index_type>': PieCharts,
    '/api/charts/pie': AllPieCharts,
    '/api/cmc/id': CmcId,
    '/api/cmc/ids': CmcIds,
    '/api/indices': AllIndices,
    '/api/supported_assets': SupportedAssets,
    '/api/supported_exchanges': SupportedExchanges,
    '/api/supported_exchange_assets': SupportedExchangeAssets,
    '/api/supported_exchange_pairs': SupportedExchangePairs,


    '/api/cube': CubeResource,
    '/api/cube/allocations/current': AllocationsCurrent,
    '/api/cube/allocations/target': AllocationsTarget,
    '/api/cube/available_ex_assets': AvailableAssets,
    '/api/cube/balances': Balances,
    '/api/cube/connection': ConnectionResource,
    '/api/cube/ex_pairs': ExPairResource,
    '/api/cube/save_setting': SaveCubeSetting,
    '/api/cube/transactions': Transactions,
    '/api/cube/valuations': Valuations,


    '/health': Healthcheck,
}

for key, value in resources.items():

    api.add_resource(value, key)

    docs.register(value)

# Build the database:
# This will create the database file using SQLAlchemy
try:
    init_db()
    print('DB INITALIZED')
except:
    app.logger.exception('Empty database. Unable to run init_db().')

# This error handler is necessary for webargs usage with Flask-RESTful.
@parser.error_handler
def handle_request_parsing_error(err, req):
    abort(422, errors=err.messages)

if __name__ == '__main__':
    PORT = int(os.getenv('PORT'))
    HOST = os.getenv('HOST')
    print ("Starting server..")


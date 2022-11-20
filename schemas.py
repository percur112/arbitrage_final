from marshmallow import Schema, fields


class AlgorithmSchema(Schema):
    active = fields.Bool()
    name = fields.Str()
    features = fields.List(fields.Str())


class AssetSchema(Schema):
    asset = fields.Str()
    percent = fields.Decimal()


class CurrencySchema(Schema):
    symbol = fields.Str()
    name = fields.Str()
    market_cap = fields.Int()
    cmc_id = fields.Str()
    percent_change_24h = fields.Decimal()
    percent_change_7d = fields.Decimal()


class ExchangeSchema(Schema):
    name = fields.Str()
    key = fields.Str()
    secret = fields.Str()
    passphrase = fields.Str()
    video_url = fields.Str()
    signup_url = fields.Str()
    id = fields.Int()


class ExchangeAssetsSchema(Schema):
    name = fields.Str()
    signup_url = fields.Str()
    assets = fields.List(fields.Nested(CurrencySchema))
    id = fields.Int()


class ExPairSchema(Schema):
    base_symbol = fields.Str()
    quote_symbol = fields.Str()
    exchange_id = fields.Int()


class BalanceSchema(Schema):
    currency = fields.Nested(CurrencySchema)
    exchange = fields.Nested(ExchangeSchema)
    total = fields.Decimal()
    target = fields.Decimal()
    btc_rate = fields.Decimal()



class IndicesSchema(Schema):
    type = fields.Str()
    count = fields.Int()
    currencies = fields.List(fields.Nested(CurrencySchema))


class APIConnectionsSchema(Schema):
    exchange = fields.Nested(ExchangeSchema)
    failed_at = fields.DateTime()


class CubeCacheSchema(Schema):
    processing = fields.Bool()


class OrderSchema(Schema):
    amount = fields.Decimal()
    avg_price = fields.Decimal()
    datetime = fields.Str()
    ex_pair = fields.Nested(ExPairSchema)
    order_id = fields.Str()
    side = fields.Str()
    price = fields.Decimal()
    filled = fields.Decimal()
    unfilled = fields.Decimal()
    timestamp = fields.Str()


class CubeSchema(Schema):
    algorithm = fields.Nested(AlgorithmSchema)
    api_connections = fields.List(fields.Nested(APIConnectionsSchema))
    auto_rebalance = fields.Bool()
    balanced_at = fields.DateTime()
    btc_data = fields.Bool()
    closed_at = fields.DateTime()
    cube_cache = fields.Nested(CubeCacheSchema)
    exchange = fields.Nested(ExchangeSchema)
    fiat = fields.Nested(CurrencySchema)
    fiat_id = fields.Int()
    id = fields.Int()
    index = fields.Nested(IndicesSchema)
    is_rebalancing = fields.Bool()
    orders = fields.List(fields.Nested(OrderSchema))
    reallocated_at = fields.DateTime()
    rebalance_interval = fields.Int()
    risk_tolerance = fields.Int()
    supported_assets = fields.List(fields.Str())
    threshold = fields.Decimal()
    trading_status = fields.Str()
    unrecognized_activity = fields.Bool()
    wide_charts = fields.Bool()
    name = fields.Str()


class CubeLimitedSchema(Schema):
    algorithm = fields.Nested(AlgorithmSchema)
    api_connections = fields.List(fields.Nested(APIConnectionsSchema))
    auto_rebalance = fields.Bool()
    balanced_at = fields.DateTime()
    fiat = fields.Nested(CurrencySchema)
    is_rebalancing = fields.Bool()
    orders = fields.List(fields.Nested(OrderSchema))
    reallocated_at = fields.DateTime()
    rebalance_interval = fields.Int()
    risk_tolerance = fields.Int()
    supported_assets = fields.List(fields.Str())
    threshold = fields.Decimal()
    trading_status = fields.Str()


class PieChartSchema(Schema):
    name = fields.Str()
    y = fields.Decimal()


class IndexPieChartSchema(Schema):
    index_type = fields.Str()
    chart = fields.List(fields.Nested(PieChartSchema))


class SupportedAssetsSchema(Schema):
    header = fields.List(fields.Str())
    values = fields.List(fields.List(fields.Str()))


class TransactionSchema(Schema):
    datetime = fields.Str()
    base_symbol = fields.Str()
    quote_symbol = fields.Str()
    base_amount = fields.Decimal()
    quote_amount = fields.Decimal()
    price = fields.Decimal()
    type = fields.Str()
    price = fields.Decimal()
    tx_id = fields.Str()


class UserApiKeySchema(Schema):
    key = fields.Str()


class UserNotificationSchema(Schema):
    id = fields.Int()
    type = fields.Str()
    message = fields.Str()


class UserSchema(Schema):
    api_keys = fields.List(fields.Nested(UserApiKeySchema))
    available_algorithms = fields.List(fields.Nested(AlgorithmSchema))
    available_exchanges = fields.List(fields.Nested(ExchangeSchema))
    email = fields.Email()
    first_name = fields.Str()
    email_confirmed = fields.Bool()
    otp_complete = fields.Bool()
    is_pro = fields.Bool()
    is_basic = fields.Bool()
    btc_data = fields.Bool()
    wide_charts = fields.Bool()
    portfolio = fields.Bool()
    fiat = fields.Nested(CurrencySchema)
    fiat_id = fields.Int()
    notifications = fields.List(fields.Nested(UserNotificationSchema))
    open_cubes = fields.List(fields.Nested(CubeSchema))
    role = fields.Str()
    social_id = fields.Str()
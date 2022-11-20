from flask_restful import abort
from flask_apispec import MethodResource, marshal_with, doc
from schemas import IndexPieChartSchema
from database import Indices


@marshal_with(IndexPieChartSchema(many=True))
@doc(tags=['Charts'], 
    description='Index pie chart by index_name='\
    'top_five, top_ten, top_twenty, top_thirty, top_fifty, top_hundred'\
    ' index_type= mcw (market cap weighted), ew (equally weighted)')
class PieChart(MethodResource):
    def get(self, index_type, index_name):
        try:
            full_index_name = f'{index_name}_{index_type}'
            pie_chart = []
            index = Indices.query.filter_by(type=index_name).first()
            if index_type == 'mcw':
                # Market Capitalization Weighted
                # Total USD value of all assets
                total_cap = 0
                for cur in index.currencies:
                    total_cap += cur.market_cap
                # List of dictionaries with symbol/percent
                for cur in index.currencies:
                    percent = cur.market_cap / total_cap
                    pie_chart.append({'name': cur.symbol,
                                           'y': float(percent)})

            if index_type == 'ew':
                for cur in index.currencies:
                    percent = 1 / len(index.currencies)
                    pie_chart.append({'name': cur.symbol,
                                           'y': float(percent)}) 

            return [{ 'index_type': full_index_name, 'chart': pie_chart }]                   
        except:
            abort(500, message='Something went wrong')


@marshal_with(IndexPieChartSchema(many=True))
@doc(tags=['Charts'], description='All index pie charts'\
    ' index_type= mcw (market cap weighted), ew (equally weighted)')
class PieCharts(MethodResource):
    def get(self, index_type):
        try:
            pie_charts = []
            indices = Indices.query.all()
            for index in indices:
                full_index_name = f'{index.type}_{index_type}'
                pie_chart = []
                if index_type == 'mcw':
                    # Market Capitalization Weighted
                    # Total USD value of all assets
                    total_cap = 0
                    for cur in index.currencies:
                        total_cap += cur.market_cap
                    # List of dictionaries with symbol/percent
                    for cur in index.currencies:
                        percent = cur.market_cap / total_cap
                        pie_chart.append({'name': cur.symbol,
                                               'y': float(percent)})
                if index_type == 'ew':
                    for cur in index.currencies:
                        percent = 1 / len(index.currencies)
                        pie_chart.append({'name': cur.symbol,
                                               'y': float(percent)})  
                                                                  
                pie_charts.append({ 'index_type': full_index_name,
                                    'chart': pie_chart })

            return pie_charts
        except:
            abort(500, message='Something went wrong')

@marshal_with(IndexPieChartSchema(many=True))
@doc(tags=['Charts'], description='All market cap weighted index pie charts')
class AllPieCharts(MethodResource):
    def get(self):
        try:
            pie_charts = []
            indices = Indices.query.all()
            for index in indices:
                pie_chart = []

                total_cap = 0
                for cur in index.currencies:
                    total_cap += cur.market_cap

                for cur in index.currencies:
                    percent = cur.market_cap / total_cap
                    pie_chart.append({'name': cur.symbol,
                                           'y': float(percent)})

                pie_charts.append({ 'index_type': index.type,
                                    'chart': pie_chart })

            return pie_charts
        except:
            abort(500, message='Something went wrong')


@doc(tags=['Charts'], 
    description='All indices and assets: \
    [{"top_ten": [{"name": "NEO","y": 0.0112},{...}]}..]')
class AllIndices(MethodResource):
    def get(self):
        try:
            pie_charts = []
            indices = Indices.query.all()
            for index in indices:
                pie_chart = {}

                total_cap = 0
                for cur in index.sorted_currencies:
                    total_cap += cur.market_cap

                for cur in index.sorted_currencies:
                    percent = cur.market_cap / total_cap
                    pie_chart[cur.symbol] = float(percent)
                pie_charts.append([ index.type, pie_chart ])

            return pie_charts
        except:
            abort(500, message='Something went wrong')
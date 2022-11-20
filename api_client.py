import requests
from requests_toolbelt.utils import dump

###########################################################
######### Fetching Newest Market Data #####################


_baseurl = 'https://coincube.io/api/v1/'
auth_args = {'key': '', 'secret': ''}

def cube_details(cube_id):
    url = _baseurl + 'cube_details'
    data = {**auth_args, **{
        'cube_id': cube_id
    }}
    # POST request
    r = requests.post(url, data=data)
    # Return JSON data
    content = r.json()
    if r.status_code == 200:
        return content
    else:
        return "There was a problem: " + str(r.status_code)

def get_portfolios(algorithm_id=6):
    url = _baseurl + 'get_portfolios'
    data = {**auth_args, **{
        'algorithm_id': algorithm_id
    }}
    # POST request
    r = requests.post(url, data=data)
    # Return JSON data
    content = r.json()
    if r.status_code == 200:
        return content
    else:
        return "There was a problem: " + str(r.status_code)

def post_allocations(allocations, algorithm_id=6):
    url = _baseurl + 'post_allocations'
    data = {**auth_args, **{
        'allocations': allocations,
        'algorithm_id': algorithm_id
    }}
    # POST request
    r = requests.post(url, json=data)
    data = dump.dump_all(r)
    # Return 'success' or status code
    if r.status_code == 200:
        return "success"
    else:
        return "There was a problem: " + str(r.status_code)



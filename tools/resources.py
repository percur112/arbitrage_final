from flask_restful import abort


def pruneArgs(args):
    return {k: v for k, v in args.items() if v is not missing} 

def check_cube_access(cube, current_user):

    if cube.user_id == current_user.id:
        return True
    abort(403)
    

def check_user_access(user, current_user):
    if user.id == current_user.id:
        return True

    abort(403)
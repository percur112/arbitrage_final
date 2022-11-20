from database import *


BASE_RATE = 1

class Account(object):

    def __init__(self, user):
        self.user = user

    def was_notified(self, type, entity_id = None):
        return UserNotification.query.filter(
            UserNotification.type == type,
            UserNotification.user_id == self.user.id,
            UserNotification.entity_id == entity_id
        ).count() > 0

    def clear_notification(self, type, entity_id = None):
        return UserNotification.query.filter(
            UserNotification.type.like("%" + type + "%"),
            UserNotification.user_id == self.user.id,
            UserNotification.entity_id == entity_id
        ).delete()


    def get_ledger_total(self):
        total = 0
        for entry in self.user.ledger_entries:
            total += entry.amount

        return total
    

    def log_notification(self, type, entity_id = None):
        notification = UserNotification(
            user_id = self.user.id,
            entity_id = entity_id,
            type = type)
        db_session.add(notification)
        db_session.commit()


def reset_cube(cube_id):
    try:
        AssetAllocation.query.filter_by(cube_id=cube_id).delete()
        Balance.query.filter_by(cube_id=cube_id).delete()
        Connection.query.filter_by(cube_id=cube_id).delete()
        ConnectionError.query.filter_by(cube_id=cube_id).delete()
        CubeUserAction.query.filter_by(cube_id=cube_id).delete()
        CubeCache.query.filter_by(cube_id=cube_id).delete()
        Order.query.filter_by(cube_id=cube_id).delete()
        Transaction.query.filter_by(cube_id=cube_id).delete()
        custom_ports = CustomPortfolio.query.filter_by(cube_id=cube_id).all()
        for custom in custom_ports:
            db_session.delete(custom)
        return True
    except:
        return False

def delete_cube(cube_id):
    try:
        if reset_cube(cube_id):
            cube = Cube.query.filter_by(id=cube_id).first()
            db_session.delete(cube)
            db_session.commit()
            return True
    except:
        return False
   
def reset_user(user_id):
    try:
        # Delete records
        cubes = Cube.query.filter_by(user_id=user_id).all()
        for cube in cubes:           
            delete_cube(cube.id)
        Cube.query.filter_by(user_id=user_id).delete()
        db_session.commit()
        # Update user record
        user = User.query.filter_by(id=user_id).first()
        user.portfolio = 0
        db_session.add(user)
        db_session.commit()
        return True
    except:
        return False

def delete_user(user_id):
    try:
        if reset_user(user_id):
            ConnectionError.query.filter_by(user_id=user_id).delete()
            UserApiKey.query.filter_by(user_id=user_id).delete()
            UserNotification.query.filter_by(user_id=user_id).delete()
            User.query.filter_by(id=user_id).delete()
            db_session.commit()
            return True
    except:
        return False
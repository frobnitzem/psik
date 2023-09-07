# catch-all for psik exceptions:
class AnException(Exception):
    pass

# Note: chain exceptions using 'except Exception, e: raise InvalidJobException from e'
class InvalidJobException(AnException):
    pass

class SubmitException(AnException):
    pass

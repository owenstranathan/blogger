
from functools import wraps
import inspect

# courtesy of Nadi Alramli via SO, Thanks! https://stackoverflow.com/questions/1389180/automatically-initialize-instance-variables
# updated to use python3 getfullargspec
def initializer(func):
    """
    Automatically assigns the parameters to the class of the function it wraps
    """
    fullspec = inspect.getfullargspec(func)
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        for name, arg in list(zip(fullspec.args[1:], args)) + list(kwargs.items()): # starting the zip at idx 1 excludes `self` and then we just grab the kwargs
            setattr(self, name, arg)
        if fullspec.defaults:
            for name, default in zip(reversed(fullspec.args), reversed(fullspec.defaults)):
                if not hasattr(self, name):
                    setattr(self, name, default)
        func(self, *args, *kwargs)
    return wrapper


#TODO (owen) DOC: This can be imported by the user via
#`from __main__ import UserExtension` anything from this file can be imported in this way
# WARNING: this is kind of a dangerous pattern because it means any kind of user code can be run, so don't use
# blogger to compile strange websites that you didn't write
class UserExtension():
    """
    A user definied extension to the blogger app
    """
    def __init__(self, logger, working_dir, out_dir, site_data, jinja_env):
        pass

    def pre_render_post(self, name, post):
        pass

    def post_render_post(self, name, post):
        pass

    def should_skip_template(self, name, template, posts):
        """
        This function gives the user-extension the ability to short cut the template rendering offered by  blogger.
        Using this function you can short cut the regular template rendering and render the template yourself and write it where ever you like
        return FALSE to let blogger render and write out the template
        return TRUE to tell blogger to skip the template and instead let you handle it
        NOTE: there can be multiple user extensions runninng and anyone of them may skip the template
        """
        pass

    def finalize(self):
        pass


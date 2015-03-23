'''
Created on Mar 12, 2015

@author: derigible
'''

from django.conf.urls import url, patterns
from django.conf import settings
import importlib as il
import glob, os, sys, inspect
from django.views.generic.base import View

def check_if_list(lst):
    if isinstance(lst, str):
        '''
        Since strings are also iterable, this is used to make sure that the iterable is a non-string. Useful to ensure
        that only lists, tuples, etc. are used and that we don't have problems with strings creeping in.
        '''
        raise TypeError("Must be a non-string iterable: {}".format(lst))
    if not (hasattr(lst, "__getitem__") or hasattr(lst, "__iter__")):
        raise TypeError("Must be an iterable: {}".format(lst))

class Routes(object):
    '''
    A way of keeping track of routes at the view level instead of trying to define them all inside the urls.py. The hope
    is to make it very straightforward and easy without having to resort to a lot of custom routing code. This will be
    accomplished by writing routes to a list and ensuring each pattern is unique. It will then add any pattern mapppings
    to the route for creation of named variables. An optional ROUTE_AUTO_CREATE setting can be added in project settings
    that will create a route for every app/controller/view and add it to the urls.py.
    '''
    
    routes = [] #Class instance so that lazy_routes will add to the routes table without having to add from the LazyRoutes list.
    acceptable_routes = ('app_module_view', 'module_view')
    tracked = set() #single definitive source of all routes
    
    def __init__(self):
        '''
        Initialiaze the routes object by creating a set that keeps track of all unformatted strings to ensure uniqueness.
        '''
        #Check if the urls.py has been loaded, and if not, then load it (for times when you want to create the urls without loading Django completely)
        proj_name_urls = __name__.split('.')[0] + '.urls'
        if proj_name_urls not in sys.modules:
            il.import_module(proj_name_urls)
        if hasattr(settings, "ROUTE_AUTO_CREATE"):
            if settings.ROUTE_AUTO_CREATE == "app_module_view":
                self._register_installed_apps_views(settings.INSTALLED_APPS, with_app = True)
            elif settings.ROUTE_AUTO_CREATE == "module_view":
                self._register_installed_apps_views(settings.INSTALLED_APPS)
            else:
                raise ValueError("The route_auto_create option was set in settings but option {} is not a valid option. Valid options are: {}".format(settings.route_auto_create, self.acceptable_routes))
    
    def _register_installed_apps_views(self, apps, with_app = False):
        '''
        Set the routes for all of the installed apps (except the django.* installed apps). Will search through each module
        in the installed app and will look for a view class. If a views.py module is found, any functions found in the 
        module will also be given a routing table by default. Each route will, by default, be of the value <module_name>.<view_name>. 
        If you are worried about view names overlapping between apps, then use the with_app flag set to true and routes 
        will be of the variety of <app_name>.<module_name>.<view_name>. The path after the base route will provide positional 
        arguments to the url class for anything between the forward slashes (ie. /). For example, say you have view inside 
        a module called foo, your route table would include a route as follows:
        
            ^foo/view_name/(?([^/]*)/)*
        
        Note that view functions that are not class-based must be included in the top-level directory of an app in a file
        called views.py if they are to be included. This does not make use of the Django app loader, so it is safe to put
        models in files outside of the models.py, as long as those views are class-based.
        
        Note that class-based views must also not require any parameters in the initialization of the view.
        
        To prevent select views from not being registered in this manner, set the register_route variable on the view to False.
        
        All functions within a views.py module are also added with this view. That means that any decorators will also have
        their own views. If this is not desired behavior, then set the settings.REGISTER_VIEWS_PY_FUNCS to False.
            
        @param apps: the INSTALLED_APPS setting in the settings for your Django app.
        @param with_app: set to true if you want the app name to be included in the route
        '''
        def add_func(app, mod, func):
            r = "{}/{}/(?:([^/])*/+)*".format(mod,func[0])
            if with_app:
                r = "{}/{}".format(app, r)
            self.add(r, func[1], add_ending=False)
            
        for app in settings.INSTALLED_APPS:
            if 'django' != app.split('.')[0]: #only do it for non-django apps
                loaded_app = il.import_module(app)
                for p in glob.iglob(os.path.join(loaded_app.__path__[0], '*.py')):
                    mod = p.split(os.sep)[-1][:-3]#get just the module name without the .py
                    try:
                        loaded_mod = il.import_module('.' + mod, loaded_app.__package__)
                        for klass in inspect.getmembers(loaded_mod, inspect.isclass):
                            try:
                                inst = klass[1]()
                                if isinstance(inst, View):
                                    if not hasattr(inst, 'register_route') or(hasattr(inst, 'register_route') and inst.register_route):
                                        add_func(app, mod, klass)
                                    if hasattr(inst, 'routes'):
                                        self.add_view(klass[1])
                            except TypeError: #not a View class if init is required.
                                pass
                        if mod == "views" and (hasattr(settings, 'REGISTER_VIEWS_PY_FUNCS') and settings.REGISTER_VIEWS_PY_FUNCS):
                            for func in inspect.getmembers(loaded_mod, inspect.isfunction):
                                add_func(app, mod, func)
                    except ImportError:
                        raise TypeError("Routes type found in view module when settings.ROUTE_AUTO_CREATE has been set. Switch Routes to LazyRoutes.")
        
    def add(self, route, func, var_mappings= None, add_ending=True, **kwargs):
        '''
        Add the name of the route, the value of the route as a unformatted string where the route looks like the following:
        
        /app/{var1}/controller/{var2}
        
        where var1 and var2 are arbitrary place-holders for the var_mappings. The var_mappings is a list of an iterable of values
        that match the order of the format string passed in. If no var_mappings is passed in it is assumed that the route has no mappings
        and will be left as is.
        
        Unformatted strings must be unique. Any unformatted string that is added twice will raise an error.
        
        To pass in a reverse url name lookup, you can use the key word 'django_url_name' in the kwargs dictionary.
        
        @route the unformatted string for the route
        @func the view function to be called
        @var_mappings the list of dictionaries used to fill in the var mappings
        @add_ending adds the appropriate /$ is on the ending if True. Defaults to True
        @kwargs the kwargs to be passed into the urls function
        '''
        self._check_if_format_exists(route)
        
        def add_url(pattern, pmap, ending, opts):
            url_route = '^{}{}'.format(pattern.format(*pmap), '/$' if ending else '')
            if "django_url_name" in opts:
                url_obj = url(url_route, func, kwargs, name=kwargs['django_url_name'])
            else:
                url_obj = url(url_route, func, kwargs)
            self.routes.append(url_obj)
            
        if var_mappings:
            for mapr in var_mappings:
                check_if_list(mapr)
                add_url(route, mapr, add_ending, kwargs)
        else:
            add_url(route, [], add_ending, kwargs)
    
    def add_list(self, routes, func, prefix=None, **kwargs):
        '''
        Convenience method to add a list of routes for a func. You may pass in a prefix to add to each
        pattern. For example, each url needs the word workload prefixed to the url to make: workload/<pattern>.
        
        Note that the prefix should have no trailing slash.
        
        A route table is a dictionary after the following fashion:
        
        {
         "pattern" : <pattern>', 
         "map" :[('<regex_pattern>',), ...],
         "kwargs" : dict
        }
        
        @routes the list of routes
        @func the function to be called
        @prefix the prefix to attach to the route pattern
        '''
        check_if_list(routes)
        for route in routes:
            if 'kwargs' in route:
                if type(route['kwargs']) != dict:
                    raise TypeError("Must pass in a dictionary for kwargs.")
                for k, v in route["kwargs"].items():
                    kwargs[k] = v
            self.add(route["pattern"] if prefix is None else '{}/{}'.format(prefix, route["pattern"]),
                      func, var_mappings = route.get("map", []), **kwargs)
    
    @property
    def urls(self):
        '''
        Get the urls from the Routes object. This a patterns object.
        '''
        return patterns(r'',*self.routes)
        
    def _check_if_format_exists(self, route):
        '''
        Checks if the unformatted route already exists.
        
        @route the unformatted route being added.
        '''
        if route in self.tracked:
            raise ValueError("Cannot have duplicates of unformatted routes: {} already exists.".format(route))
        else:
            self.tracked.add(route)
            
    def add_view(self, view, **kwargs):
        '''
        Add a class-based view to the routes table. A view that is added to the routes table must define the routes table; ie:
        
            (
                  {"pattern" : <pattern>', 
                   "map" :[('<regex_pattern>',), ...],
                   "kwargs" : dict
                   },
                 ...
            )
        
        Kwargs can be ommitted if not necessary.
        
        Optionally, if the view should have a prefix, then define the variable prefix as a string; ie
        
            prefix = 'workload'
            
            or
            
            prefix = 'workload/create
            
        Note that the prefix should have no trailing slash.
        '''
        if not hasattr(view, 'routes'):
            raise AttributeError("routes variable not defined on view {}".format(view.__name__))
        if hasattr(view, 'prefix'):
            prefix = view.prefix
        else:
            prefix = None
        
        self.add_list(view.routes, view.as_view(), prefix = prefix, **kwargs)

class LazyRoutes(Routes):
    '''
    A lazy implementation of routes. This means that LazyRoutes won't add routes to the Routes table until after the
    routes table has been created. This is necessary when the ROUTE_AUTO_CREATE setting is added to the Django settings.py.
    All defined routes using the routes.* method must now become lazy_routes.* methods.
    '''
    
    def __init__(self):
        '''
        Do nothing, just overriding the base __init__ to prevent the initilization there.
        '''
        pass
        
lazy_routes = LazyRoutes()
routes = Routes()
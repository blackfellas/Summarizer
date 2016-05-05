#!/usr/bin/env python
# -*- coding: utf-8 -*-

import praw
import logging, logging.config, sys, os
from ConfigParser import SafeConfigParser
import psycopg2

r = None
cfg_file = SafeConfigParser()
path_to_cfg = os.path.abspath(os.path.dirname(sys.argv[0]))
path_to_cfg = os.path.join(path_to_cfg, 'cred.cfg')
cfg_file.read(path_to_cfg)

def login():
    try:
        r = praw.Reddit(user_agent=cfg_file.get('reddit', 'user_agent'))
        r.set_oauth_app_info(cfg_file.get('reddit', 'client_id'), cfg_file.get('reddit', 'client_secret'), cfg_file.get('reddit', 'redirect_uri'))
        r.refresh_access_information(cfg_file.get('reddit', 'refresh_token'))
        
    except Exception as e:
        logging.error(e)
        print ('trying old methods...')
        try:
            logging.debug('Logging in as {0}'
                      .format(cfg_file.get('reddit', 'username')))
            r.login(cfg_file.get('reddit', 'username'),
                cfg_file.get('reddit', 'password'), disable_warning=False)
        except Exception as e:
            logging.error(e)
            
    finally:
        return r
    
def conn():
    dbname = cfg_file.get('database', 'database')
    dbuser = cfg_file.get('database', 'user')
    dbpassword = cfg_file.get('database', 'password')
    dbhost = cfg_file.get('database', 'host')
    
    try:    
        con = psycopg2.connect(database=dbname, user=dbuser, password=dbpassword, host=dbhost)
        print('connected to database: ' + dbname)
        return con
    except Exception as e:
        logging.error(e)
    return

if __name__ == '__main__':
    print 'login.py'
    login()
else:
    print 'login module imported'
    

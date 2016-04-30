# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division, print_function, unicode_literals

from goose import Goose
from sumy.parsers.plaintext import PlaintextParser
from sumy.parsers.html import HtmlParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer as Summarizer
from sumy.nlp.stemmers import Stemmer
from sumy.utils import get_stop_words


import urllib2
from breadability.readable import Article


import os, sys, re
from datetime import datetime
from time import sleep

from login import login
from ConfigParser import SafeConfigParser
import psycopg2


#convert time to unix time
def timestamp(dt, unix=datetime(1970,1,1)):
    td = dt - unix
    # return td.total_seconds()
    return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6 

now = datetime.utcnow()
print (now)
print (int(timestamp(now)))




#blacklist ((or regex) to ignore
#s - submission
def blacklist(b_list, s):
    domain = s.domain.lower()
    subreddit = 'self.' + str(s.subreddit.display_name).lower()  
    if domain == subreddit:
        return True
    
    #convert string to list items    
    b_list = b_list.split('\r\n') 
    for regex in b_list:
        regex = regex.strip()
        if regex == '':
            continue
        pattern = re.compile(regex, re.UNICODE|re.IGNORECASE)
        if pattern.search(domain):
            print('  regex match: ', regex, '|', domain)
            return True
    return False


#user names made lowercase
def visited(s, bot):
    try:
        for comment in s.comments:
            if comment.author == bot and comment.is_root:
                print ('  Not doing this again')
                return True 
    except Exception as e:
        print(e)
        return True
        
    return False
    

def summary(s, length, LANGUAGE):
    #cookie handling websites like NYT
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())  
    response = opener.open(s.url)
    raw_html = response.read()
    

    g = Goose()
    meta = g.extract(raw_html=raw_html).meta_description
    raw_article = str(Article(raw_html))
    compression = 100
    
    #Breadability+Goose for cleaner text?
    article = g.extract(raw_html=raw_article)
    text = article.cleaned_text      
    
    language = LANGUAGE.lower()
    stemmer = Stemmer(language)
    summarizer = Summarizer(stemmer)
    summarizer.stop_words = get_stop_words(language)
    
    #choose parser
    if len(text) == 0 or len(text) < len(meta):
        print('  ...using HTML parser')
        text = raw_article
        parser = HtmlParser(text, Tokenizer(language))
    else:
        parser = PlaintextParser(text, Tokenizer(language))    
    
    short = []
    line = str()
    for sentence in summarizer(parser.document, length):
        line = '>* {0}'.format(str(sentence).decode('utf-8'))
        line = line.replace("`", "\'")
        line = line.replace("#", "\#")
        short.append(line)        

    extract = '\n'.join(short)
    try:
        compression = int(len(extract)/len(text)*100)
    except Exception as e:
        print(' ', e)
    extract = '{0}\n\n---\n{1}'.format(meta, extract)
    #print (extract.encode('utf-8'), compression, '%')
    print('  from {0} words to {1} words ({2}%)'.format(text.count(' '), extract.count(' '), compression))
    return extract, compression
    
    

def main():
    #global reddit session
    r = None
    cfg_file = SafeConfigParser()
    path_to_cfg = os.path.abspath(os.path.dirname(sys.argv[0]))
    path_to_sch = os.path.join(path_to_cfg, 'schedulebot.cfg')
    cfg_file.read(path_to_sch)
    r = login()
    bot = r.get_redditor(cfg_file.get('reddit', 'username'))

    
    # connect to db and get data
    dbname = cfg_file.get('database', 'database')
    dbuser = cfg_file.get('database', 'user')
    dbpassword = cfg_file.get('database', 'password')
    dbhost = cfg_file.get('database', 'host')
    
    conn = psycopg2.connect(database=dbname, user=dbuser, password=dbpassword, host=dbhost)
    cur = conn.cursor()
    cur.execute('SELECT * FROM summarize')
    subreddits = cur.fetchall()
    
    for sub in subreddits:
        # do the subs from the db table
        print ('\nProcessing', sub[0], '...')
        now = datetime.utcnow()
        current_sub = r.get_subreddit(sub[0])
        
         
        length = sub[1]
        b_list = sub[2]
        language = sub[3]
        last_run = sub[5]
        new_run = last_run
        processed = 0

        try:
            submissions = current_sub.get_new(limit=15, fetch=True)
        except Exception as h:
            print('Ugh! Reddit', h)
            sleep(60)
            continue
        
        for s in submissions:
            #http error 429
            s = s
            print ('\n\n', s.url)
            if s.created_utc <= last_run:
                print ('  not recent')
                continue
            if blacklist(b_list, s):
                print ('  blacklisted')
                continue
            if visited(s, bot):
                continue
            try:                
                result = summary(s, length, language)

                if result[1] > 50:
                    print ('  Big Summary:', result[0].encode('utf-8'))
                    continue
                if len(result[0]) < 300:
                    print ('  Too short!')
                    continue
                print ('\n\n')
                print (' ', s.title, '-', s.domain, result[1], '%')
                print (' ', result[0].encode('utf-8'))
                url = s.url
                url = url.replace('(', '\(')
                url = url.replace(')', '\)')
                more = '\n\n---\n\n[**more here...**]({0} "Compressed to {1}% of original - click to read the full article") ^(*I\'m just a bot*)'.format(url, result[1])
                print (more)
                
                try:
                     s.add_comment(result[0] + more)
                     processed += 1    
                except Exception as e:
                    print(e)
                    continue
                   
            except Exception as e:
                if str(e).lower().strip() == "HTTP Error 404: Not Found".lower():
                    print ('  404: dead link')
                    s.set_flair(flair_css_class='current', flair_text='404: dead link')
                else:
                    print(' ',e)
                continue
            #store update time
            new_run = int(timestamp(now))
        #check if unchanged
        print('\n---\n ', processed, 'article(s) summarized')
        if last_run == new_run: 
            print ('  no more new posts!')
        last_run = new_run    
        cur.execute("update summarize set last_run = %s where subreddit = %s", (last_run, sub[0]))
    cur.close()
    conn.commit()
    
    
if __name__ == '__main__':
    main()

      
    
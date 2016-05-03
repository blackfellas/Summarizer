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


import os, sys, re, time
from datetime import datetime
from time import sleep

from login import login, conn
from ConfigParser import SafeConfigParser

#import alerts
import random
from math import log

#global reddit session
global r
global session
r = None
cfg_file = SafeConfigParser()
path_to_cfg = os.path.abspath(os.path.dirname(sys.argv[0]))
path_to_sch = os.path.join(path_to_cfg, 'cred.cfg')
cfg_file.read(path_to_sch)

r = login()
session = conn()

#convert time to unix time
def timestamp(dt, unix=datetime(1970,1,1)):
    td = dt - unix
    # return td.total_seconds()
    return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6 


print (datetime.utcnow())
print (int(timestamp(datetime.utcnow())))

def ProcessMessages(bot, last_message):
    #look for thing_id
    pattern = re.compile(r't1_\S+', re.MULTILINE|re.DOTALL|re.UNICODE)
    processed = 0
    new_messages = 0
    unsubscribe = []
    #cur = session.cursor()
    try:
        for message in r.get_inbox():
            if int(message.created_utc) <= last_message:
                break
            if message.was_comment:
                continue
            if message.subject.strip().lower() == 'unsubscribe':
                unsubscribe.append(message.author.name)
            if message.subject.strip().lower() == 'delete':
                new_messages += 1
                #obtain a list of ids in comments
                things = pattern.findall(message.body)
                if not things:
                    continue
                for ids in things:
                    comment = r.get_info(thing_id=ids)
                    if comment.is_root and comment.author.name == bot.name and message.author.name == comment.submission.author.name:
                        #try to remove it else delete (if no mod privileges)                        
                        try:                        
                            comment.remove()
                        except:
                            try:
                                comment.delete()
                            except:
                                continue
                        processed += 1
        print('  new_messages: ' + str(new_messages))
        print('  deleted: ' + str(processed))
    except Exception as e:
        print('  '+ str(e))
    finally:
        return set(unsubscribe)

#blacklist ((or regex) to ignore
#s - submission
def blacklist(b_list, s):    
    if s.domain.lower() == 'self.' + str(s.subreddit.display_name).lower():
        return True
    #remove in live version; dev-only
    if str(s.subreddit.display_name).lower() == 'blackfellas':
        return True
    #convert string to list items
    b_list = b_list.split('\r\n')    
    for regex in b_list:
        regex = regex.strip()
        if regex == '':
            continue
        pattern = re.compile(regex, re.UNICODE|re.IGNORECASE)
        if pattern.search(s.domain):
            print('  regex match: ', pattern.search(s.domain).group(0))
            return True
    return False


#user names made lowercase
def visited(comments, bot):
    
    try:
        for comment in comments:
            if comment.author == bot and comment.is_root:
                print ('  Not doing this again')
                return True 
    except Exception as e:
        #ignore if unsure, so return True
        print(e + ' on revisit')
        return True
        
    return False
    

def summary(s, length, LANGUAGE):
    g = Goose() 
    #cookie handling websites like NYT       
    #except HTTP 403 error
    try:    
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())  
        response = opener.open(s.url)
        raw_html = response.read()
        raw_article = str(Article(raw_html))
        meta = g.extract(raw_html=raw_html).meta_description
    except Exception as e:
        print ('  ' + str(e))
        raw_html = g.extract(url=s.url)
        raw_article = raw_html.cleaned_text
        meta = raw_html.meta_description

    
    
    compression = 100
    #Breadability+Goose for cleaner text?
    article = g.extract(raw_html=raw_article)
    text = article.cleaned_text      
    word_count = text.count(' ')
    
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
    #length = int(round(log(word_count, 3), 0))
    for sentence in summarizer(parser.document, length):
        line = '>* {0}'.format(str(sentence).decode('utf-8'))
        line = line.replace("`", "\'")
        line = line.replace("#", "\#")
        short.append(line)        

    extract = '\n'.join(short)
    try:
        compression = int(len(extract)/len(text)*100)
        print(" ", len(text), 'chars in text')
    except Exception as e:
        print(' ', e)
    #print (extract.encode('utf-8'), compression, '%')
    print('  from {0} words to {1} words ({2}%)'.format(word_count, extract.count(' '), compression))
    return meta, extract, compression
    
    

def main():

    bot = r.get_redditor(cfg_file.get('reddit', 'username'))
    
    
    # connect to db and get data
    cur = session.cursor()
    cur.execute('SELECT * FROM summarize')
    subreddits = cur.fetchall()
    #inbox only needs to be checked once, so obtain latest value
    cur.execute('SELECT max(last_message) FROM summarize')
    last_message = cur.fetchone()[0]
    #reset if empty
    if not last_message:
        last_message = 0
    
    #check delete messages
    print('  checking inbox...')
    now = datetime.utcnow()
    try:    
        ProcessMessages(bot, last_message)
        #update check
        last_message = int(timestamp(now))
    except Exception as e:
        print ('  error reading from inbox: ' + str(e))
        pass

    for sub in subreddits:
        # do the subs from the db table
        print ('\nProcessing', sub[0], '...')
        now = datetime.utcnow()
        current_sub = r.get_subreddit(sub[0])
        
        #database table 
        length = sub[1] #number of keypoints in summary
        b_list = sub[2] #blacklisted websites
        language = sub[3] #english
        #excluded = sub[4] #unsubscribed/excluded users
        last_run = sub[5] #time last active
        last_time = datetime.fromtimestamp(last_run).strftime('%Y-%m-%d %H:%M:%S')
        print ('  last ran: '+ last_time)
        new_run = last_run
        processed = 0
              
        
        try:
            submissions = current_sub.get_new(limit=15, fetch=True)
        except Exception as h:
            print('  Ugh! Reddit', h)
            continue
        try:
            for s in submissions:
                #http errors happen here 
                s = s
                url = s.url
                print ('\n\n', url)
                
                if s.created_utc <= last_run:
                    print ('  not recent')
                    continue
                
                if blacklist(b_list, s):
                    print ('  blacklisted')
                    continue
                
                comments = s.comments
                #check if processed and update last_run time
                if visited(comments, bot):
                    new_run = int(timestamp(now))
                    continue
                try:                
                    meta, extract, compression = summary(s, length, language)
                    #store update time here
                    
                    if compression > 66:
                        print ('  Big Summary:', extract.encode('utf-8'))
                        continue
                    if len(extract) < 200 or compression < 1:
                        print ('  Too short!', extract.encode('utf-8'))
                        continue
                    
                    print ('\n\n')
                    print (' ', s.title, '-', s.domain)
                    print (' ', extract.encode('utf-8'))
                    url = s.url
                    url = url.replace('(', '\(')
                    url = url.replace(')', '\)')
                    extract = '{0}\n\n---\n{1}'.format(meta, extract)
                    more = '\n\n---\n\n[**more here...**]({0} "Compressed to {1}% of original - click to read the full article") ^(*I\'m just a bot*) | '.format(url, compression)
                    print (more)
                    
                    try:
                         post = s.add_comment(extract + more)
                         comment_id = 't1_' + post.id
                         msg = '[delete](https://www.reddit.com/message/compose/?to={0}&subject=delete&message=comment id: {1})'.format(bot.name, comment_id)
                         post.edit(post.body + msg)
                         processed += 1    
                    except Exception as e:
                        print('  error posting comment'+str(e))
                        continue
                    
                    new_run = int(timestamp(now))
                       
                except Exception as e:
                    if str(e).lower().strip() == "HTTP Error 404: Not Found".lower():
                        print ('  404: dead link')
                        smiley = random.sample(['dead','rosedead', 'pacquiao'], 1)
                        s.add_comment('[](#{0}) Link is dead?'.format(smiley[0]))
                        s.set_flair(flair_css_class='current', flair_text='404: dead link')
                        
                    else:
                        print(' ',e)
                    continue
        except Exception as e:
            print ('  Reddit error: ' + str(e))
            print ('  sleeping...')
            sleep(60)
            continue
        #check if unchanged
        print('\n---\n ', processed, 'article(s) summarized')
        if last_run == new_run: 
            print ('  no more new posts!')
        last_run = new_run
        cur.execute("update summarize set last_message = %s where subreddit = %s", (last_message, sub[0]))
        cur.execute("update summarize set last_run = %s where subreddit = %s", (last_run, sub[0]))
    cur.close()
    session.commit()
    

    
    
if __name__ == '__main__':
    t1 = time.clock()
    main()
    t2 = time.clock()
    t3 = round(t2-t1, 3)
    print ('\n  all done in', t3, 'secs')
      
    
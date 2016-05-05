#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division, print_function, unicode_literals

from goose import Goose
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer as Summarizer
from sumy.nlp.stemmers import Stemmer
from sumy.utils import get_stop_words
from math import log
import urllib3, urllib2, cookielib
import re

from datetime import datetime
from time import sleep
from login import login, conn

#start global reddit session
global r
r = None
r = login()
session = conn()

#convert time to unix time
def timestamp(dt, unix=datetime(1970,1,1)):
    td = dt - unix
    # return td.total_seconds()
    return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6 


print (datetime.utcnow())


def ProcessMessages(bot, last_message):
    #look for thing_id to delete
    pattern = re.compile(r't1_\S+', re.MULTILINE|re.DOTALL|re.UNICODE)
    processed = 0
    new_messages = 0
    unsubscribe = []
    blacklist = []
    
    try:
        for message in r.get_inbox():
            if int(message.created_utc) <= last_message:
                break
            if message.was_comment:
                continue
            if message.subject.strip().lower() == 'unsubscribe':
                print('  unsubscribe message from: ', message.author.name)
                #tuple (user, subreddit as body)
                unsubscribe.append((message.author.name.lower(), message.body.strip().lower()))
                continue
            if 'blacklist:' in message.subject.strip().lower():
                sub = message.subject.replace('blacklist:', '').strip()
                if message.author in r.get_moderators(sub):               
                    print ('  new blacklist message in: ', sub) 
                    #tuple (blacklist: subreddit as subject, site as body)
                    blacklist.append((sub.lower(), message.body.strip().lower()))
                continue           
            if message.subject.strip().lower() == 'delete':
                new_messages += 1
                #obtain a list of ids in comments
                things = pattern.findall(message.body)
                if not things:
                    continue
                for ids in things:
                    try:
                        comment = r.get_info(thing_id=ids)
                        if (comment.is_root and comment.author.name == bot.name and message.author.name == comment.submission.author.name) or message.author in r.get_moderators(comment.subreddit.display_name):
                        #try to remove it else delete (if no mod privileges)                        
                            try:                        
                                comment.remove()
                            except:
                                try:
                                    comment.delete()
                                except:
                                    continue
                        processed += 1
                    except: #deleted comment probably
                        continue
        print('  new_messages: ' + str(new_messages))
        print('  deleted: ' + str(processed))
    except Exception as e:
        print('  some error:'+ str(e))
    finally:
        return set(unsubscribe), set(blacklist)



#blacklist ((or regex) to ignore
#s - submission
def blacklist(b_list, e_list, s):
    domain = s.domain.lower()
    subreddit = 'self.' + str(s.subreddit.display_name).lower()  
    if domain == subreddit:
        return True
    
    #convert string to list items
    b_list = b_list.split() if b_list else []
    for regex in b_list:
        regex = regex.strip()
        if regex == '':
            continue
        pattern = re.compile(regex, re.IGNORECASE)
        if pattern.search(s.domain):
            print('  regex match: ', pattern.search(s.domain).group(0))
            return True
    
    e_list = e_list.split() if e_list else []
    for user in e_list:
        if not user:
            continue
        user = user.strip().lower()
        if s.author.name.lower() == user:
            print ('  user blacklist: ', user)
            return True
    return False


#user names made lowercase
def visited(s, bot):
    try:
        for comment in s.comments:
            if comment.author == bot and comment.is_root:
                return True 
    except Exception as e:
        print(e)
        return True        
    return False

def check_comment_votes(bot):
    comments = bot.get_comments(sort='new', time='all')
    for c in comments:
        try:
            if c.score < 0:
                print ('  removing downvoted comment ' + c.id )
                try: #
                    c.remove()
                except:
                    c.delete()                   
        except: #score hidden
            pass        

def summary(url, length, LANGUAGE):
    #cookie handling websites like NYT
    e = None
    try:
        cj = cookielib.CookieJar()
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))  
        response = opener.open(url)
        raw_html = response.read()    
    #403 errors...    
    except Exception as e:     
        try:
            http = urllib3.PoolManager()
            response = http.urlopen('GET', url)
            raw_html = response.data.decode('utf-8')
        except Exception as e:
            return e

    g = Goose()
    meta = g.extract(raw_html=raw_html).meta_description
    article = g.extract(raw_html=raw_html)
    text = article.cleaned_text
    word_count = len(text.split())
    compression = 100
            
    language = LANGUAGE.lower()
    stemmer = Stemmer(language)
    summarizer = Summarizer(stemmer)
    summarizer.stop_words = get_stop_words(language) 
    parser = PlaintextParser(text, Tokenizer(language))    
    
    short = []
    line = str()
    if word_count >= 500:
        length = length + int(log(word_count/100))
    for sentence in summarizer(parser.document, length):
        line = '>* {0}'.format(str(sentence).decode('utf-8'))
        line = line.replace("`", "\'")
        line = line.replace("#", "\#")
        short.append(line)        
    extract = '\n'.join(short)
    try:
        compression = int((extract.count(' ')/word_count)*100)
        print(" ", len(text), 'chars in text. keypoints:', length)
    except:
        pass
    print('  from {0} words to {1} words ({2}%)'.format(word_count, len(extract.split()), compression))
    return (meta, extract, compression, e)
    


def main():
    bot = r.get_me()
    
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
    print('  checking inbox...')
    now = datetime.utcnow()
    #check delete messages
    try:    
        excluded, black_list = ProcessMessages(bot, last_message)
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
        #database table summarize
        length = sub[1] #number of keypoints in summary
        b_list = sub[2] #blacklisted websites
        language = sub[3] #english
        e_list = sub[4] #unsubscribed/excluded users
        last_run = sub[5] #time last active
        #algorithm = sub[6]
        LIMIT = sub[8] #number of submissions to fetch
        
        last_time = datetime.fromtimestamp(last_run).strftime('%Y-%m-%d %H:%M:%S')
        print ('  last ran: '+ last_time)
        new_run = last_run
        print ('  last run:', new_run)
        processed = 0
        
        #unsubscribe list
        e_list = e_list.split() if e_list else []
        for unsubs in excluded:
        #(subject as unsubscribe, body as subreddit)
            if unsubs[1] == sub[0].lower():
                e_list.append(unsubs[0])
        e_list = set(e_list)
        e_list = '\r\n'.join(e_list)      
        #blacklist        
        b_list = b_list.split() if b_list else []
        for site in black_list:
        #(subreddit in subject, body as  site)
            in_sub = site[0]
            if in_sub.lower() == sub[0].lower():
                b_list.append(site[1])
        b_list = set(b_list)
        b_list = '\r\n'.join(b_list)        
  
        try:
            submissions = current_sub.get_new(limit=LIMIT, fetch=True)
        except Exception as h:
            print('Ugh! Reddit', h)
            sleep(60)
            continue       
        for s in submissions:
            #http error 429
            url = s.url
            print ('\n\n', url)
            #store update time
            new_run = int(s.created_utc) if s.created_utc > new_run else new_run
            if s.created_utc <= last_run:
                print ('  reached end of last run')
                break
            #give a fellow bot a fist 
            if s.author.name.lower() == 'automoderator':
                    s.vote(1)               
            if blacklist(b_list, e_list, s):
                print ('  blacklisted')
                continue           
            if visited(s, bot):
                print ('  already visited')
                break
            try:                
                result = summary(url, length, language)
                meta, extract, compression, e = result
                if hasattr(e, 'code'):
                    if e.code == 404:
                        s.set_flair(flair_text='404: dead link')
                        continue
                #check compression
                if compression > 60:
                    print ('  Big Summary:\n', extract.encode('utf-8'))
                    continue
                #check extracted text length
                if len(extract.split()) < 120:
                    print ('  Too short!')
                    continue              
                #formatting for reddit markup, add meta description
                extract = '{0}\n\n---\n{1}'.format(meta, extract)
                print ('\n')
                print (' ', s.title, '-', s.domain)
                print (' ', extract.encode('utf-8'))
                print('====================================================')
                #more reddit mark up
                url = s.url
                url = url.replace('(', '\(')
                url = url.replace(')', '\)')
                more = '\n\n[**more here...**]({0} "Compressed to {1}% of original - click to read the full article")\n\n---\n\n'.format(url, compression)
                print (more)                
                try:
                     post = s.add_comment(extract + more)
                     comment_id = 't1_' + post.id
                     msg_1 = '  [^(delete)](https://www.reddit.com/message/compose/?to={0}&subject=delete&message=comment id\(s\): {1} "submitter can delete this comment")'.format(bot.name, comment_id)
                     msg_2 = ' ^| [^(unsubscribe)](https://www.reddit.com/message/compose/?to={0}&subject=unsubscribe&message={1} "unsubscribe the bot from your posts")'.format(bot.name, sub[0])
                     msg_3 = ' ^| [^(blacklist)](https://www.reddit.com/message/compose/?to={0}&subject=blacklist: {1}&message={2} "blacklist this article\'s website (mods)")'.format(bot.name, sub[0], s.domain)
                     msg_4 = ' ^| [^(*I\'m just a bot*)](https://github.com/blackfellas/Summarizer)'
                     post.edit(post.body + msg_1 + msg_2 + msg_3 + msg_4)
                     processed += 1    
                except Exception as e:
                    print('  ' + str(e))
                    continue                  
            except Exception as e:
                print (' Possible urllib3 HTTP error:' + str(e))
                continue            
        #check if unchanged
        print('\n---\n ', processed, 'article(s) summarized')
        if last_run == new_run: 
            print ('  unchanged since last ran')
        last_run = new_run    
        cur.execute("update summarize set last_run = %s where subreddit = %s", (last_run, sub[0]))
        cur.execute("update summarize set excluded = %s where subreddit = %s", (e_list, sub[0]))
        cur.execute("update summarize set blacklist = %s where subreddit = %s", (b_list, sub[0]))
        cur.execute("update summarize set last_message = %s where subreddit = %s", (last_message, sub[0]))      
    cur.close()
    session.commit()
    
    
if __name__ == '__main__':
    main()

      
    
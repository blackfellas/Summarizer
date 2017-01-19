#!/usr/bin/env python
# -*- coding: utf-8 -*-


from newspaper import Article
from xreadability import Readability
from html import unescape
from unicodedata import normalize
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer as Summarizer
from sumy.nlp.stemmers import Stemmer
from sumy.utils import get_stop_words
from math import log
import re

from datetime import datetime
from time import sleep
from login import login, conn

#start global reddit session
global r
r = None
r = login()
session = conn()
print (' ', datetime.utcnow().strftime("%c"))

#convert time to unix time
def timestamp(dt, unix=datetime(1970,1,1)):
    td = dt - unix
    # return td.total_seconds()
    return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6 

def summary(url, length, LANGUAGE):
    language = LANGUAGE.lower()
    e = str() #capture error

    article = Article(url)
    try:    
        article.download()
        print ('  successfully d/l')
        article.parse()
        raw_html = article.html
        image = article.top_image
        meta = article.meta_description
        text = article.text
    except Exception as e:
        print(e)
 
    if not text:
        print ('  using Readability')
        raw_text = Readability(raw_html, url)
        text = raw_text.content
        article.download(html=text)
        article.parse()
        text = article.text
    if not meta:
        meta = article.title
    meta = unescape(unescape(meta))
    meta = normalize('NFKD', meta)
    meta = meta.strip()
    image = image.replace('(', '\(')
    image = image.replace(')', '\)')
    image_des = '\n\n> [{0}]({1})'.format("**^pic**", image) if image else None  
   
    parser = PlaintextParser(text, Tokenizer(language)) 
    word_count = len(text.split())
    compression = 100
    extra_words = 0
            
    stemmer = Stemmer(language)
    summarizer = Summarizer(stemmer)
    summarizer.stop_words = get_stop_words(language)        
    short = []
    line = str()
    
    if word_count >= 600:
        length = length + int(log(word_count/600))
    for sentence in summarizer(parser.document, length):
        if str(sentence).strip().lower() in meta.lower():
            extra_words = len(str(sentence).split())
            continue
        line = '>• {0}'.format(sentence)
        line = line.replace("`", "\'")
        line = line.replace("#", "\#")
        short.append(line)
       
    extract = '\n\n'.join(short)
    extract = extract + image_des if image_des else extract
    meta = meta.replace('#', '\#')
    if len(meta) > 400:
       lpoint = meta.rfind('.', 0, 400)
       if lpoint == -1:
           meta = meta[:(meta.rfind(' ', 0, 400))] + '...'
       else:
           meta = meta[:(meta.rfind('.', 0, 400))] + '...'
              
    try:
        compression = int(((extract.count(' ')+extra_words)/word_count)*100)
    except Exception as numerror:
        print(numerror)
    print('  from {0} words to {1} words ({2}%)'.format(word_count, len(extract.split()), compression))
    return (meta, extract, compression, e)
    
        
def main():
    bot = r.user.me()
    
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
        current_sub = r.subreddit(sub[0])        
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
            submissions = current_sub.new(limit=LIMIT)
        except Exception as h:
            print('  Oops! Reddit is down', h)
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
 
            if blacklist(b_list, s):
                print ('  blacklisted')
                continue           
            if visited(s, bot):
                print ('  already visited this')
                continue
            try:                
                result = summary(url, length, language)
                meta, extract, compression, e = result
                if hasattr(e, 'code'):
                    if e.code == 404:
                        try:
                            s.add_comment("This link appears to be dead, Jim.")
                            s.set_flair(flair_text='404: dead link')
                        except:
                            continue
                #check compression
                if compression > 60:
                    print ('  Big Summary:\n', extract)
                    continue
                #check extracted text length
                if len(extract.split()) < 80:
                    print ('  Too short!\n ', extract)
                    continue              
                extract = '{0}\n\n***\n{1}'.format(meta, extract)
                print ('\n')
                print (' ', s.title, '-', s.domain)
                print (' ', extract)
                
                #more reddit mark up
                url = s.url
                url = url.replace('(', '\(')
                url = url.replace(')', '\)')
                more = ' [**^^full ^^story** ^^|]({0} "Compressed to {1}% of original - click to read the full article")'.format(url, compression)
                print('='*70)             
                try:
                     post = s.reply(extract + '\n\n***\n\n')
                     comment_id = 't1_' + post.id
                     msg_1 = '  [^^(**delete**)](https://www.reddit.com/message/compose/?to={0}&subject=delete&message=comment id\(s\): {1} "submitter can delete this comment")'.format(bot.name, comment_id)
                     msg_2 = ' ^^| [^^(**blacklist**)](https://www.reddit.com/message/compose/?to={0}&subject=blacklist: {1}&message={2} "blacklist this article\'s website (mods)")'.format(bot.name, sub[0], s.domain)
                     msg_3 = ' ^^| [^^(**github**)](https://github.com/blackfellas/Summarizer "I\'m just a bot")'
                     msg_4 = ' ^^| [^^(**theory**)](https://en.wikipedia.org/wiki/Latent_semantic_analysis)\n' #|-|-|-|-|
                     post.edit(post.body + more + msg_1 + msg_2 + msg_3 + msg_4)
                     processed += 1    
                except Exception as e:
                    print('  ' + str(e))
                    continue                  
            except Exception as e:
                print (str(e))
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
    #remove downvoted posts
    check_comment_votes(bot)

def ProcessMessages(bot, last_message):
    #look for thing_id to delete
    pattern = re.compile(r't1_\S+', re.MULTILINE|re.DOTALL|re.UNICODE)
    processed = 0
    new_messages = 0
    unsubscribe = []
    blacklist = []
    
    try:
        for message in r.inbox.all():
            message.mark_read()
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
                sub = r.subreddit(sub)
                if message.author in sub.moderator:               
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
                        comment = r.comment(ids)
                        sub = comment.subreddit
                        if (comment.is_root and comment.author.name == bot.name and message.author.name == comment.submission.author.name) or (message.author in sub.moderator):
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
def blacklist(b_list, s):
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
    print ('  checking for downvoted comments')
    comments = bot.comments.new()
    for c in comments:
        try:
            if c.score < 0:
                if c.edited or c.approved: #manually edited
                    continue
                print ('    removing downvoted comment ' + c.id )
                try: #to remove else delete
                    c.remove()
                except:
                    c.delete()                   
        except: #score hidden
            pass        




    
if __name__ == '__main__':
    main()

      
    

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sopdsdb
import sopdsparse
import time
import datetime
import sopdscfg
import base64
import zipf
import logging

class opdsScanner:
    def __init__(self, cfg, logger):
        self.cfg=cfg
        self.logger=logger
        self.opdsdb=None
        self.fb2parser=None
        self.init_stats()
        self.init_parser()
        zipf.ZIP_CODEPAGE=self.cfg.ZIP_CODEPAGE
        self.extensions_set={x for x in self.cfg.EXT_LIST}

    def init_stats(self):
        self.t1=datetime.timedelta(seconds=time.time())
        self.t2=self.t1
        self.books_added   = 0
        self.books_skipped = 0
        self.books_deleted = 0
        self.arch_scanned = 0
        self.arch_skipped = 0
        self.bad_archives = 0
        self.books_in_archives = 0

    def init_parser(self):
        self.fb2parser=sopdsparse.fb2parser(self.cfg.COVER_EXTRACT)

    def log_options(self):
        self.logger.info(' ***** Starting sopds-scan...')
        self.logger.debug('OPTIONS SET')
        if self.cfg.CONFIGFILE!=None:     self.logger.debug('configfile = '+self.cfg.CONFIGFILE)
        if self.cfg.ROOT_LIB!=None:       self.logger.debug('root_lib = '+self.cfg.ROOT_LIB)
        if self.cfg.FB2TOEPUB_PATH!=None: self.logger.debug('fb2toepub = '+self.cfg.FB2TOEPUB_PATH)
        if self.cfg.FB2TOMOBI_PATH!=None: self.logger.debug('fb2tomobi = '+self.cfg.FB2TOMOBI_PATH)
        if self.cfg.TEMP_DIR!=None:       self.logger.debug('temp_dir = '+self.cfg.TEMP_DIR)

    def log_stats(self):
        self.t2=datetime.timedelta(seconds=time.time())
        self.logger.info('Books added      : '+str(self.books_added))
        self.logger.info('Books skipped    : '+str(self.books_skipped))
        if self.cfg.DELETE_LOGICAL:
            self.logger.info('Books deleted    : '+str(self.books_deleted))
        else:
            self.logger.info('Books DB entries deleted : '+str(self.books_deleted))
        self.logger.info('Books in archives: '+str(self.books_in_archives)) 
        self.logger.info('Archives scanned : '+str(self.arch_scanned))
        self.logger.info('Archives skipped : '+str(self.arch_skipped))
        self.logger.info('Bad archives     : '+str(self.bad_archives))

        t=self.t2-self.t1
        seconds=t.seconds%60
        minutes=((t.seconds-seconds)//60)%60
        hours=t.seconds//3600
        self.logger.info('Time estimated:'+str(hours)+' hours, '+str(minutes)+' minutes, '+str(seconds)+' seconds.')

    def scan_all(self):
        self.opdsdb=sopdsdb.opdsDatabase(self.cfg.DB_NAME,self.cfg.DB_USER,self.cfg.DB_PASS,self.cfg.DB_HOST,self.cfg.ROOT_LIB)
        self.opdsdb.openDB()
        self.opdsdb.avail_check_prepare()

        if self.cfg.COVER_EXTRACT:
            if not os.path.isdir(sopdscfg.COVER_PATH):
                os.mkdir(sopdscfg.COVER_PATH)

        for full_path, dirs, files in os.walk(self.cfg.ROOT_LIB):
            for name in files:
                file=os.path.join(full_path,name)
                (n,e)=os.path.splitext(name)
                if (e.lower() == '.zip'):
                    if self.cfg.ZIPSCAN:
                        self.processzip(name,full_path,file)
                else:
                    file_size=os.path.getsize(file)
                    self.processfile(name,full_path,file,0,file_size)

        self.opdsdb.commit()
        if self.cfg.DELETE_LOGICAL:
           self.books_deleted=self.opdsdb.books_del_logical()
        else:
           self.books_deleted=self.opdsdb.books_del_phisical()
        self.opdsdb.update_double()
        self.opdsdb.closeDB()
        self.opdsdb=None

    def processzip(self,name,full_path,file):
        rel_file=os.path.relpath(file,self.cfg.ROOT_LIB)
        if self.cfg.ZIPRESCAN or self.opdsdb.zipisscanned(rel_file,1)==0:
            cat_id=self.opdsdb.addcattree(rel_file,1)
            try:
                z = zipf.ZipFile(file, 'r', allowZip64=True)
                filelist = z.namelist()
                for n in filelist:
                    try:
                        self.logger.debug('Start process ZIP file = '+file+' book file = '+n)
                        file_size=z.getinfo(n).file_size
                        self.processfile(n,file,z.open(n),1,file_size,cat_id=cat_id)
                    except:
                        self.logger.error('Error processing ZIP file = '+file+' book file = '+n)
                z.close()
                self.arch_scanned+=1
            except:
                self.logger.error('Error while read ZIP archive. File '+file+' corrupt.')
                self.bad_archives+=1
        else:
            self.arch_skipped+=1
            self.logger.debug('Skip ZIP archive '+rel_file+'. Already scanned.')

    def processfile(self,name,full_path,file,archive=0,file_size=0,cat_id=0):
        (n,e)=os.path.splitext(name)
        if e.lower() in self.extensions_set:
            rel_path=os.path.relpath(full_path,self.cfg.ROOT_LIB)
            self.logger.debug("Attempt to add book "+rel_path+"/"+name)
            self.fb2parser.reset()
            if self.opdsdb.findbook(name,rel_path,1)==0:
               if archive==0:
                  cat_id=self.opdsdb.addcattree(rel_path,archive)
               title=''
               lang=''
               annotation=''
               docdate=''
               fnpat=''
               ictype=''

               if e.lower()=='.fb2' and self.cfg.FB2PARSE:
                  if isinstance(file, str):
                     f=open(file,'rb')
                  else:
                     f=file
                  self.fb2parser.parse(f,self.cfg.FB2HSIZE)
                  f.close()

                  if len(self.fb2parser.lang.getvalue())>0:
                     lang=self.fb2parser.lang.getvalue()[0].strip(' \'\"')
                  if len(self.fb2parser.book_title.getvalue())>0:
                     title=self.fb2parser.book_title.getvalue()[0].strip(' \'\"\&-.#\\\`')
                  if len(self.fb2parser.annotation.getvalue())>0:
                     annotation=('\n'.join(self.fb2parser.annotation.getvalue()))[:10000]
                  if len(self.fb2parser.docdate.getvalue())>0:
                     docdate=self.fb2parser.docdate.getvalue()[0].strip();

                  if self.fb2parser.parse_error!=0:
                     self.logger.warning(rel_path+' - '+name+' fb2 parse warning ['+self.fb2parser.parse_errormsg+']')

               if title=='': title=n

               if e.lower()=='.fb2' and self.cfg.FB2PARSE and self.cfg.COVER_EXTRACT:
                  (fnpat,ictype)=self.cover_meta()

               book_id=self.opdsdb.addbook(name,rel_path,cat_id,e,title,annotation,docdate,lang,file_size,archive,self.cfg.DUBLICATES_FIND, fnpat, ictype)
               self.books_added+=1

               if e.lower()=='.fb2' and self.cfg.FB2PARSE and self.cfg.COVER_EXTRACT and fnpat!='':
                  try:
                    fn=fnpat.format(book_id)
                    self.cover_save(fn)
                  except:
                    self.logger.error('Error extract cover from file '+name) 

#                  try:
#                    self.create_cover(book_id)
#                  except:
#                    self.logger.error('Error extract cover from file '+name)

               if archive==1:
                  self.books_in_archives+=1
               self.logger.debug("Book "+rel_path+"/"+name+" Added ok.")

               idx=0
               for l in self.fb2parser.author_last.getvalue():
                   last_name=l.strip(' \'\"\&-.#\\\`')
                   first_name=self.fb2parser.author_first.getvalue()[idx].strip(' \'\"\&-.#\\\`')
                   author_id=self.opdsdb.addauthor(first_name,last_name)
                   self.opdsdb.addbauthor(book_id,author_id)
                   idx+=1
               for l in self.fb2parser.genre.getvalue():
                   self.opdsdb.addbgenre(book_id,self.opdsdb.addgenre(l.lower().strip(' \'\"')))
               for l in self.fb2parser.series.getattrs('name'):
                   self.opdsdb.addbseries(book_id,self.opdsdb.addseries(l.strip()))
               if not self.cfg.SINGLE_COMMIT: self.opdsdb.commit()

            else:
               self.books_skipped+=1
               self.logger.debug("Book "+rel_path+"/"+name+" Already in DB.")
    
    def cover_meta(self):
        ictype=self.fb2parser.cover_image.getattr('content-type')
        coverid=self.fb2parser.cover_image.getattr('id')
        fn=''
        e='.img'
        if ictype==None:
           ictype=''
        else:
           ictype=ictype.lower()
           if ictype=='image/jpeg' or ictype=='image/jpg':
              e='.jpg'
           elif ictype=='image/png':
              e='.png'
           elif coverid!=None:
             (f,e)=os.path.splitext(coverid)
           else:
             e='.img'
           fn='{}'+e
        return (fn,ictype)

    def cover_save(self,fn):
        fp=os.path.join(sopdscfg.COVER_PATH,fn)
        if len(self.fb2parser.cover_image.cover_data)>0:
           img=open(fp,'wb')
           s=self.fb2parser.cover_image.cover_data
           dstr=base64.b64decode(s)
           img.write(dstr)
           img.close()

    def create_cover(self,book_id):
        ictype=self.fb2parser.cover_image.getattr('content-type')
        coverid=self.fb2parser.cover_image.getattr('id')
        fn=''
        if ictype==None:
           ictype=''
        else:
           ictype=ictype.lower()
           if ictype=='image/jpeg' or ictype=='image/jpg':
              fn=str(book_id)+'.jpg'
           else:
              if ictype=='image/png':
                 fn=str(book_id)+'.png'
              else:
                 if coverid!=None:
                    (f,e)=os.path.splitext(coverid)
                 else:
                    e='.img'
                 fn=str(book_id)+e

           fp=os.path.join(sopdscfg.COVER_PATH,fn)
           if len(self.fb2parser.cover_image.cover_data)>0:
              img=open(fp,'wb')
              s=self.fb2parser.cover_image.cover_data
              dstr=base64.b64decode(s)
              img.write(dstr)
              img.close()
        self.opdsdb.addcover(book_id,fn,ictype)


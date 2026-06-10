#!/bin/bash
cd /home/lab-admin/price-monitor
./venv/bin/python3 -u -c "
import sys; sys.path.insert(0,'src'); import logging,time
logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',handlers=[logging.FileHandler('logs/crawl_wandashan.log',mode='w')])
from services.xdotool_crawler import XdotoolCrawler
c=XdotoolCrawler(); r=c.crawl_keyword('完达山学乐奶粉')
print('RESULT:', r)
" &
echo "Started"

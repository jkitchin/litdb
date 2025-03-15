"""Crawl a website and add each page to a litdb."""

from docling.document_converter import DocumentConverter
from tqdm import tqdm
from .db import add_source

import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy import signals
from scrapy.signalmanager import dispatcher


class LinkExtractorSpider(scrapy.Spider):
    """Class for link extractor."""

    name = "link_extractor"

    def __init__(self, start_url, *args, **kwargs):
        """Construct a spider instance."""
        super(LinkExtractorSpider, self).__init__(*args, **kwargs)
        self.start_urls = [start_url]

    def parse(self, response):
        """Extract all links from the response."""
        links = response.css('a::attr(href)').getall()
        for link in links:
            # Construct absolute URL
            absolute_url = response.urljoin(link)
            yield {'link': absolute_url}


def extract_links(root_url):
    """Generate each link in a web-page."""
    extracted_links = []

    def handle_item(item, response, spider):
        extracted_links.append(item['link'])

    # Connect the signal handler to the item_scraped signal
    dispatcher.connect(handle_item, signal=signals.item_scraped)

    # Set up the crawling process
    process = CrawlerProcess(settings={
        # Options: CRITICAL, ERROR, WARNING, INFO, DEBUG
        "LOG_LEVEL": "ERROR"})
    process.crawl(LinkExtractorSpider, start_url=root_url)
    process.start()  # The script will block here until the crawling is finished

    # Yield each extracted link
    for link in extracted_links:
        yield link


def spider(root):
    """Crawl through root and add documents to litdb."""
    converter = DocumentConverter()
    for url in tqdm(extract_links(root)):
        print(url)

        try:
            md = converter.convert(url).document.export_to_markdown()
            add_source(url, md, {'from': 'crawl'})
        except Exception as e:
            print(e)

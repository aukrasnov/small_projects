import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
import logging
import datetime
import psycopg2
from configparser import ConfigParser
import smtplib
import ssl

insert_tpl = '''INSERT INTO public.alerts 
(current_dt, news_dt, stock_name, news_subject, url, news_text, news_dt_price, current_dt_price) 
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)'''


def config(filename, section):
    parser = ConfigParser()
    parser.read(filename)

    con = {}
    if parser.has_section(section):
        params = parser.items(section)
        for param in params:
            con[param[0]] = param[1]
    else:
        raise Exception('Section {0} not found in the {1} file'.format(section, filename))

    return con


def articles_urls():
    response = requests.get('https://mfn.se/all/s')
    content = BeautifulSoup(response.content, "html.parser")
    article_urls = []

    for article in content.find_all(
            class_='short-item-wrapper grid-u-1 grid-u-md-1-2 grid-u-lg-1-3 grid-u-xl-1-4 removable-grid'):
        url = article.find(class_='short-item compressible').get('onclick').replace("goToNewsItem(event, '",
                                                                                    '').replace("')", '')
        article_urls.append(f'https://mfn.se{url}')

    return article_urls


def article_content(article_url):
    response = requests.get(article_url)
    content = BeautifulSoup(response.content, "html.parser")

    company = str(content.find(class_='tray company').getText().replace('\n', ''))
    dt = datetime.datetime.strptime(
        content.find(class_='full-item').find(class_='publish-date').getText().replace('\n', '').strip(),
        '%Y-%m-%d %H:%M:%S')
    subject = content.find(class_='').find(class_='title').getText().replace('\n', '')
    text = content.find(class_='full-item').find(class_='mfn-preamble').getText().replace('\n', '')
    text += content.find(class_='full-item').find(
        class_='publish-date').find_next_sibling().getText().replace('\n', '')[:400-len(text)]

    return {'company': company, 'dt': dt, 'subject': subject, 'text': text, 'url': article_url}


def articles_info():
    response = requests.get('https://mfn.se/all/s')
    content = BeautifulSoup(response.content, "html.parser").find_all(
        class_='short-item-wrapper grid-u-1 grid-u-md-1-2 grid-u-lg-1-3 grid-u-xl-1-4 removable-grid')
    articles = []

    for article in content[:4]:
        url = article.find(class_='short-item compressible').get('onclick').replace("goToNewsItem(event, '",
                                                                                    '').replace("')", '')
        company = content[0].find(class_='compressed-author').getText().replace('\n', '')
        d = content[0].find(class_='compressed-date').getText().replace('\n', '')
        t = content[0].find(class_='compressed-time').getText().replace('\n', '')
        dt = datetime.datetime.strptime('{} {}'.format(d, t), '%Y-%m-%d %H:%M:%S')
        url = f'https://mfn.se{url}'

        articles.append({'company': company, 'url': url, 'dt': dt})

    return articles


def get_article_price(content):
    patterns = ['\$(\d*[.,]?\d*) per Common Share', 'price/share, EUR</td><td>(\d*[.,]?\d*)</td><td>',
                'Keskihinta/ osake</td><td>(\d*[.,]?\d*)</td><td>', 'at an average price of NOK (\d*[.,]?\d*)',
                'at an average price per share of NOK (\d*[.,]?\d*)', 'shares at NOK (\d*[.,]?\d*) pr share',
                '(\d*[.,]?\d*) per share', '(\d*[.,]?\d*) per share', '[Pp]?rice per share (\d*[.,]?\d*)(\d*[.,]?\d*)']
    pattern_matches = []

    for pattern in patterns:
        pattern_matches += re.findall(pattern, content.replace('\n', ' '))

    prices = []
    for price in pattern_matches:
        try:
            price = float(price.replace(',', '.'))

            if price > 0:
                prices.append(price)
        except:
            pass

    return prices[0] if prices else False


def company_page(company):
    headers = {
        "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
                      ' Chrome/78.0.3904.87 Safari/537.36'}
    response = requests.get(f'https://www.investing.com/search/?q={urllib.parse.quote(company)}', headers=headers)
    content = BeautifulSoup(response.content, "html.parser")
    url = 'https://www.investing.com{}'.format(content.find(class_='js-inner-all-results-quote-item row').get('href'))

    return url


def company_stock_price(company):
    url = company_page(company)
    headers = {
        "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
                      ' Chrome/78.0.3904.87 Safari/537.36'}
    response = requests.get(url, headers=headers)
    content = BeautifulSoup(response.content, "html.parser")
    price = content.find(id='quotes_summary_current_data').find(class_='inlineblock').find(id='last_last').getText()

    return float(price)


def send_email(subject, text, receiver_email):
    sender_email = config('config.ini', 'sender')['email']
    password = config('config.ini', 'sender')['password']
    message = """From: Radar Plus
Subject: {}

{}
""".format(subject, text.encode('ascii', 'ignore').decode('ascii')).encode('utf-8')

    context = ssl.create_default_context()
    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message)


def get_current_price(company):  # @TODO
    return 2


def main():
    conn = psycopg2.connect(**config('config.ini', 'database'))
    receiver_email = config('config.ini', 'receiver')['email']
    articles = articles_urls()

    for article_url in articles:
        article = article_content(article_url)
        article_price = get_article_price(article['text'])
        current_price = get_current_price(article['company'])
        ratio = current_price / article_price

        logging.info('''Price for {} at moment of news is {}. Current stock price is {}. Ratio = {}
            Article {}'''.format(article['company'], article_price, current_price,
                                 ratio, article['url']))

        if article_price and ratio > 1.03:
            subject = '''Price for {} at moment of news is {}. Current stock price is {}. Ratio {}'''\
                .format(article['company'], article_price, current_price, ratio)
            text = '{} \n\n {} \n\n Url: {}'.format(article['subject'], article['text'], article['url'])

            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM public.alerts WHERE url = '{}' ".format(article['url']))
                already_sent = cursor.fetchone()

                if not already_sent:

                    send_email(subject, text, receiver_email)
                    logging.info('Email sent')

                    cursor.execute(insert_tpl, (
                        datetime.datetime.now(), article['dt'], article['company'], article['subject'], article['url'],
                        article['text'], article_price, current_price))
                    conn.commit()
                    logging.info('Row inserted')
                else:
                    logging.info('Artilce {} already in database'.format(article['url']))

    conn.close()


logging.basicConfig(level=logging.INFO)
main()




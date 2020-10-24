from flask import Flask, render_template
from flask_paginate import Pagination, get_page_args
from configparser import ConfigParser
import psycopg2


app = Flask(__name__)
app.template_folder = ''


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


def count_news():
    conn = psycopg2.connect(**config('config.ini', 'database'))

    with conn.cursor() as cursor:

        cursor.execute('SELECT count(*) FROM  public.alerts')
        result = cursor.fetchone()

    conn.close()

    return result[0]


def get_users(offset=0, per_page=10):
    conn = psycopg2.connect(**config('config.ini', 'database'))

    sql = '''
    SELECT 
        stock_name, 
        news_dt, 
        current_dt_price/news_dt_price, 
        concat(news_subject, ' ', news_text),
        url
    FROM public.alerts 
    WHERE id <= (SELECT max(id) FROM public.alerts) - %s
    ORDER BY id DESC
    LIMIT %s'''

    with conn.cursor() as cursor:

        cursor.execute(sql, (offset, per_page))
        result = cursor.fetchall()

    conn.close()

    return result


@app.route('/')
def index():
    page, per_page, offset = get_page_args(page_parameter='page',
                                           per_page_parameter='per_page')
    total = count_news()
    pagination_users = get_users(offset=offset, per_page=per_page)
    pagination = Pagination(page=page, per_page=per_page, total=total,
                            css_framework='bootstrap4')
    return render_template('index.html',
                           users=pagination_users,
                           page=page,
                           per_page=per_page,
                           pagination=pagination,
                           )


if __name__ == '__main__':
    app.run(debug=True)

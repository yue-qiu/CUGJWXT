import time
import requests
import hashlib
import logging
from random import choice
import datetime
import pymysql
import json
from pyDes import triple_des, CBC, PAD_PKCS5

logging.basicConfig(level=logging.ERROR,
                    filename='logging.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EmptyClassroomSpider:
    def __init__(self, account, db_config):
        self.username = account.get("username")
        self.password = account.get("password")
        self.start_week = int(account.get("start"))
        self.end_week = int(account.get("end"))
        self.login_url = "http://202.114.207.137:80/ssoserver/login?ywxt=jw"
        self.login_classroom_system_url = "http://jwgl.cug.edu.cn/jwglxt/cdjy/cdjy_cxKxcdlb.html?gnmkdm=N2155&layout=default&su=20171000737"
        self.get_empty_classroom_url = "http://jwgl.cug.edu.cn/jwglxt/cdjy/cdjy_cxKxcdlb.html?doType=query&gnmkdm=N2155"
        self.session = requests.session()
        self.host = db_config.get('host')
        self.db_username = db_config.get('username')
        self.db_password = db_config.get('password')
        self.db_database = db_config.get('database')

    def log_in(self):
        key = b'neusofteducationplatform'
        iv = '01234567'
        k = triple_des(key, CBC, iv, pad=None, padmode=PAD_PKCS5)
        student_no_encrypt = k.encrypt(self.username).hex()
        md5 = hashlib.md5()
        md5.update(self.password.encode('utf-8'))
        password_encrypt = md5.hexdigest().upper()
        self.session.headers.update(
            {
                'source': 'neumobile',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Connection': 'keep-alive',
                'Accept-Encoding': 'gzip, deflate',
                'Host': 'xyfw.cug.edu.cn',
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 11_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E302',
                'Upgrade-Insecure-Requests': '1',
                'Accept-Language': 'zh-cn',
                'id_number': student_no_encrypt,
                'enp': password_encrypt
            }
        )
        # 伪装 UA
        self.session.headers.update(self.get_headers())

        try:
            res = self.session.get(self.login_url)
        except Exception as e:
            logger.error(e)
            exit(1)

        if '错误' in res.text and 'sfrz' in res.url:
            logging.error("账号密码错误")
            print('Failure. Please check logging.log')
            exit(1)

        elif '身份验证失败' in res.text and 'ssoserver' in res.url:
            logger.error("学校SSO系统故障")
            print('Failure. Please check logging.log')
            exit(1)

        try:
            self.session.get(self.login_classroom_system_url)
        except Exception as e:
            logger.error(e)
            print('Failure. Please check logging.log')
            exit(1)

        return True

    def get_empty_classroom(self, week, day, session):
        codes = {
            '北综楼': '13',
            '教三楼': '05',
            '教一楼': '06',
            '教二楼': '04',
            '东教楼': '15',

        }
        buildings = ['北综楼', '教三楼', '教二楼', '教一楼', '东教楼']

        result = {}
        for building in buildings:
            result[building] = []
            data = EmptyClassroomSpider.get_data(week, day, session, codes.get(building))

            try:
                self.session.headers.update(self.get_headers())
                r = self.session.post(data=data, url=self.get_empty_classroom_url)
            except Exception as e:
                logger.error(e)
                print('Failure. Please check logging.log')
                exit(1)

            if '用户登录' in r.text:
                logger.error("username or password error")
                print('Failure. Please check logging.log')
                exit(1)

            res = json.loads(r.text)
            for item in res.get('items'):
                result[building].append(item.get('cdmc').replace(building, ""))

        return result

    def run(self):
        self.log_in()
        session_list = {
            '1, 2': '3',
            '3, 4': '12',
            '5, 6': '48',
            '7, 8': '192',
            '9, 10': '768',
            '11, 12': '3072',
            '上午': '15',
            '下午': '240',
            '晚上': '3840',
            '白天': '255',
            '整天': '4095',
        }

        try:
            db = pymysql.connect(self.host, self.db_username, self.db_password, self.db_database)
        except Exception as e:
            logger.error(e)
            print('Failure. Please check logging.log')
            exit(1)

        cur = db.cursor()
        del_table_sql = """drop table if exists empty_classroom"""
        create_table_sql = """create table if not exists empty_classroom(
        id int UNSIGNED primary key AUTO_INCREMENT,
        date varchar(50),
        WEEK INT,
        DAY INT,
        SESSION VARCHAR(50),
        DATA LONGTEXT,
        updated_at DATETIME)"""

        try:
            cur.execute(del_table_sql)
            cur.execute(create_table_sql)
        except Exception as e:
            logger.error(e)
            print('Failure. Please check logging.log')
            exit(1)

        date = datetime.datetime.today()
        for week in range(self.start_week, self.end_week+1):
            if week == self.start_week:
                days = date.weekday()
            else:
                days = -1
            for day in range(days+1, 7):
                date = date + datetime.timedelta(days=1)
                for session in session_list:
                    # 降低速度防止被封
                    time.sleep(1)
                    data = self.get_empty_classroom(week, day, session_list.get(session))
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sql = "insert into empty_classroom(date, week, day, session, data ,updated_at) " \
                          "values ('%s', '%s', '%s', '%s', '%s', '%s')" % \
                          (date.strftime('%Y-%m-%d'), week, day, session, json.dumps(data, ensure_ascii=False), now)
                    try:
                        cur.execute(sql)
                        db.commit()
                    except Exception as e:
                        logger.error(e)
                        print('Failure. Please check logging.log')
                        db.rollback()
        cur.close()
        db.close()
        print('Succeed!')

    @staticmethod
    def get_data(week, day, session, code):
        data = {
            'fwzt': 'cx',
            'xqh_id': '1', # 学区
            'xnm': 2018,  # 学年
            'xqm': 12, # 学期，上学期3， 下学期12
            'zcd': pow(2, week-1),  # 周数, 2^(n-1)
            'xqj': day,  # 星期。2表示星期二
            'jcd': session,  # 课程。第一节为1，第二节为2，第三节为4，第四节为8，第五节为16，以此类推。如3则代表1+2,即第一节与第二节
            'lh': code,
            'jyfs': 0,
            '_search': 'false',
            'nd': int(time.time() * 1000),
            'queryModel.showCount': 100,
            'queryModel.currentPage': 1,
            'queryModel.sortName': 'cdbh',
            'queryModel.sortOrder': 'asc',
            'time': 1,
        }
        return data

    @staticmethod
    def get_headers():
        headers = [
            {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36'
                              ' (KHTML, like Gecko)'
                              ' Chrome/63.0.3239.132 Safari/537.36'
            },
            {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 11_0 like Mac OS X) AppleWebKit/604.1.38'
                              ' (KHTML, like Gecko) Version/11.0 Mobile/15A372 Safari/604.1'
            },
            {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36'
                              ' (KHTML, like Gecko) Chrome/65.0.3325.162 Mobile Safari/537.36'
            },
            {
                'User-Agent': 'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; MI 4S Build/LMY47V)'
                              ' AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 '
                              'Mobile Safari/537.36 XiaoMi/MiuiBrowser/9.1.3'
            },
            {
                'User-Agent': 'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-C7000 Build/MMB29M)'
                              ' AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 '
                              'UCBrowser/11.6.2.948 Mobile Safari/537.36'
            },
        ]

        return choice(headers)
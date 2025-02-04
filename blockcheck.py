#!/usr/bin/env python3
# coding: utf-8
import argparse
import json
import urllib.request
import urllib.parse
import urllib.error
import socket
import ssl
import sys
import os.path
import dns.resolver
import dns.exception
import ipaddress
import ipwhois

'''

=================================

IMPORTANT

Make sure to run this program with --no-report option
if you're editing it, debugging or testing something!

Thank you.

=================================

ВАЖНО

Запускайте программу с опцией --no-report, если
вы редактируете ее, отлаживаете или тестируете!

Спасибо.

=================================

'''

# Configuration
VERSION = "0.0.9.8"
SWHOMEPAGE = "https://github.com/ValdikSS/blockcheck"
SWUSERAGENT = "Blockcheck/" + VERSION + " " + SWHOMEPAGE

dns_records_list = (
    # First server in this list should have both A and AAAA records

    "rutracker.org",  # Blocked by domain name.
    "gelbooru.com",  # Only several URLs are blocked, main page is not.
    "e621.net",  # Blocked by domain name. Website is HTTP only.
    "danbooru.donmai.us",  # Blocked by root URL.
    "dailymotion.com",  # Blocked by domain name.
    "zello.com",  # Blocked by domain name.
)

http_list = {
    # Parameters:
    #    status:         HTTP response code
    #    lookfor:        Substring to search in HTTP reply body
    #    ip:             IPv4 address. Used only if hostname can't be resolved using Google API.
    #    ipv6:           IPv6 address
    #    subdomain:      This is non-blacklisted subdomain of a blacklisted domain.
    #    is_blacklisted: True if website is not blacklisted and should be treated so.

    'http://novostey.com': # This page should open in case of DPI, it's not blocked.
        {'status': 200, 'lookfor': 'novostey', 'ip': '172.64.80.1', 'ipv6': '2606:4700:130:436c:6f75:6466:6c61:7265'},

    'https://xn----stbgdeb4aai6g.xn--p1ai/': # And this should not.
        {'status': 200, 'lookfor': 'PoniBooru', 'ip': '37.1.203.158'},

    'http://a.putinhuylo.com/':
        {'status': 200, 'lookfor': 'Antizapret', 'ip': '195.123.209.38', 'subdomain': True,
         'is_blacklisted': False},
}

https_list = {'https://rutracker.org/forum/index.php', 'https://lolibooru.moe/',
              'https://e621.net/', 'https://www.dailymotion.com/'}

dpi_list =   {
    # These tests are currently performed only using IPv4. IPv6 field is not used.

    'rutracker.org':
    {'host': 'rutracker.org', 'urn': '/forum/index.php',
        'lookfor': 'groupcp.php"', 'ip': '195.82.146.214', 'ipv6': '2a02:4680:22::214'},
    'pbooru.com':
    {'host': 'pbooru.com', 'urn': '/index.php?page=post&s=view&id=304688',
        'lookfor': 'Related Posts', 'ip': '104.28.10.65', 'ipv6': '2400:cb00:2048:1::681c:a41'},
}

proxy_addr = '95.137.240.30:60030'
google_dns = '8.8.4.4'
google_dns_v6 = '2001:4860:4860::8844'
fake_dns = '3.3.3.3'  # Fake server which should never reply
fake_dns_v6 = '2600::10:20'
google_dns_api = 'https://dns.google.com/resolve'
isup_server = 'isitdownrightnow.com'
isup_fmt = 'https://www.isitdownrightnow.com/check.php?domain={}'
disable_isup = False  # If true, presume that all sites are available
disable_report = False
disable_ipv6 = False
force_ipv6 = False
force_dpi_check = False

# End configuration

ipv6_available = False
debug = False
web_interface = False

# Something really bad happened, what most likely is a bug: system DNS
# resolver and Google DNS are unavailable, while IPv6 generally work, and so on.
# Debug log is sent to server if this variable is True.
really_bad_fuckup = False

printed_text = ''
printed_text_with_debug = ''
message_to_print = ''

try:
    import tkinter as tk
    import tkinter.scrolledtext as tkst
    import threading
    import queue

    tkusable = True
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        tkusable = False


    class ThreadSafeConsole(tkst.ScrolledText):
        def __init__(self, master, **options):
            tkst.ScrolledText.__init__(self, master, **options)
            self.queue = queue.Queue()
            self.update_me()

        def write(self, line):
            self.queue.put(line)

        def clear(self):
            self.queue.put(None)

        def update_me(self):
            try:
                while 1:
                    line = self.queue.get_nowait()
                    if line is None:
                        self.delete(1.0, tk.END)
                    else:
                        self.insert(tk.END, str(line))
                    self.see(tk.END)
                    self.update_idletasks()
            except queue.Empty:
                pass
            self.after(100, self.update_me)


    def tk_terminate():
        root.destroy()
        raise SystemExit

except ImportError:
    tkusable = False


    class ThreadSafeConsole():
        pass

trans_table = str.maketrans("⚠✗✓«»", '!XV""')


def print_string(*args, **kwargs):
    message = ''
    newline = True

    for arg in args:
        message += str(arg) + " "
    message = message.rstrip(" ")
    for key, value in kwargs.items():
        if key == 'end':
            message += value
            newline = False
    if newline:
        message += "\n"

    return message


def print(*args, **kwargs):
    global printed_text, printed_text_with_debug, message_to_print
    if tkusable:
        this_text = print_string(*args, **kwargs)
        text.write(this_text)
        printed_text += this_text
        printed_text_with_debug += this_text
    else:
        if web_interface:
            message_to_print += print_string(*args, **kwargs) + "<br>"

        if args and sys.stdout.encoding != 'UTF-8':
            args = [x.translate(trans_table).replace("[☠]", "[FAIL]").replace("[☺]", "[:)]"). \
                        encode(sys.stdout.encoding, 'replace').decode(sys.stdout.encoding) for x in args
                    ]
        if not web_interface:
            __builtins__.print(*args, **kwargs)
        this_text = print_string(*args, **kwargs)
        printed_text += this_text
        printed_text_with_debug += this_text


def print_debug(*args, **kwargs):
    global printed_text_with_debug
    this_text = print_string(*args, **kwargs)
    printed_text_with_debug += this_text
    if debug:
        print(*args, **kwargs)


def really_bad_fuckup_happened():
    global really_bad_fuckup
    really_bad_fuckup = True


def _get_a_record(site, querytype='A', dnsserver=None):
    resolver = dns.resolver.Resolver()
    resolver.timeout = 5
    resolver.lifetime = 5

    if dnsserver:
        resolver.nameservers = [dnsserver]

    result = []
    while len(resolver.nameservers):
        try:
            resolved = resolver.resolve(site, querytype)
            print_debug(str(resolved.response))
            for item in resolved.rrset.items:
                result.append(item.to_text())
            return result

        except dns.exception.Timeout:
            print_debug("DNS Timeout for", site, "using", resolver.nameservers[0])
            resolver.nameservers.remove(resolver.nameservers[0])

    # If all the requests failed
    return ""


def _get_a_record_over_google_api(site, querytype='A'):
    result = []

    response = _get_url(google_dns_api + "?name={}&type={}".format(site, querytype))
    print_debug("Google API: {}".format(response))
    if (response[0] != 200):
        return ''
    response_js = json.loads(response[1])
    try:
        for dnsanswer in response_js['Answer']:
            if dnsanswer['type'] in (1, 28):
                result.append(dnsanswer['data'])
    except KeyError:
        pass
    return result


def _get_a_records(sitelist, querytype='A', dnsserver=None, googleapi=False):
    result = []
    for site in sorted(sitelist):
        try:
            if googleapi:
                responses = _get_a_record_over_google_api(site, querytype)
                print_debug("Google API вернул {}".format(responses))
            else:
                responses = _get_a_record(site, querytype, dnsserver)

            for item in responses:
                result.append(item)
        except dns.resolver.NXDOMAIN:
            print(
                "[!] Невозможно получить DNS-запись для домена {} (NXDOMAIN). Результаты могут быть неточными.".format(
                    site))
        except dns.resolver.NoAnswer:
            print_debug("DNS NoAnswer:", site)
        except dns.exception.DNSException as e:
            print_debug("DNSException:", str(e))
            really_bad_fuckup_happened()

    return sorted(result)


def _decode_bytes(input_bytes):
    return input_bytes.decode(errors='replace')


def _get_url(url, proxy=None, ip=None, headers=False, follow_redirects=True):
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def http_error_302(self, req, fp, code, msg, headers):
            infourl = urllib.response.addinfourl(fp, headers, req.get_full_url())
            infourl.status = code
            infourl.code = code
            return infourl

        http_error_300 = http_error_302
        http_error_301 = http_error_302
        http_error_303 = http_error_302
        http_error_307 = http_error_302

    parsed_url = list(urllib.parse.urlsplit(url))
    host = parsed_url[1]

    if parsed_url[0].lower() == "https":
        # Manually check certificate as we may need to connect by IP later
        # and handling certificate check in urllib is painful and invasive
        context_hostname_check = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context_hostname_check.verify_mode = ssl.CERT_REQUIRED
        conn = context_hostname_check.wrap_socket(socket.socket(socket.AF_INET6 if \
                                                                    (':' in ip if ip else False) else socket.AF_INET),
                                                  server_hostname=host)
        conn.settimeout(10)
        print_debug("_get_url: connecting over " + ('IPv6' if \
                                                        (':' in ip if ip else False) else 'IPv4'))
        try:
            conn.connect((ip if ip else host, 443))
        except (ssl.CertificateError) as e:
            print_debug("_get_url: ssl.CertificateError", repr(e))
            return (-1, '')
        except (ssl.SSLError, socket.timeout, socket.error) as e:
            print_debug("_get_url: socket exception", repr(e))
            if 'CERTIFICATE_VERIFY_FAILED' in str(e):
                return (-1, '')
            return (0, '')
        finally:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    # SSL Context for urllib
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    # Disable SSL certificate check as we validated it earlier
    # This is required to bypass SNI woes when we connect by IP
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    https_handler = urllib.request.HTTPSHandler(context=context)
    if not follow_redirects:
        # HACK: this works only for HTTP and conflicts with https_handler
        opener = urllib.request.build_opener(NoRedirectHandler, https_handler)
    else:
        opener = urllib.request.build_opener(https_handler)

    if ip:
        parsed_url[1] = '[' + str(ip) + ']' if ':' in str(ip) else str(ip)
        newurl = urllib.parse.urlunsplit(parsed_url)
        req = urllib.request.Request(newurl)
        req.add_header('Host', host)
    else:
        req = urllib.request.Request(url)

    if proxy:
        req.set_proxy(proxy, 'http')

    req.add_header('User-Agent', SWUSERAGENT)

    try:
        opened = opener.open(req, timeout=15)
        output = opened.read()
        output = _decode_bytes(output)
        if (headers):
            output = str(opened.headers) + output
        opened.close()
    except (ssl.CertificateError) as e:
        print_debug("_get_url: late ssl.CertificateError", repr(e))
        return (-1, '')
    except (urllib.error.URLError, ssl.SSLError, socket.error, socket.timeout) as e:
        print_debug("_get_url: late socket exception", repr(e))
        if 'CERTIFICATE_VERIFY_FAILED' in str(e):
            return (-1, '')
        if type(e) is urllib.error.HTTPError:
            return (e.code, '')
        return (0, '')
    except (KeyboardInterrupt, SystemExit) as e:
        # re-raise exception to send it to caller function
        raise e
    except Exception as e:
        print("[☠] Неизвестная ошибка:", repr(e))
        return (0, '')
    return (opened.status, output)


def _cut_str(string, begin, end):
    cut_begin = string.find(begin)
    if cut_begin == -1:
        return
    cut_end = string[cut_begin:].find(end)
    if cut_end == -1:
        return
    return string[cut_begin + len(begin):cut_begin + cut_end]


def get_ip_and_isp():
    # Dirty and cheap
    try:
        request = urllib.request.Request("https://2ip.ru/",
                                         headers={"User-Agent": SWUSERAGENT}
                                         )
        data = _decode_bytes(urllib.request.urlopen(request, timeout=10).read())
        ip = _cut_str(data, '<big id="d_clip_button">', '</big>')
        isp = ' '.join(_cut_str(data, '"/isp/', '</a>').replace('">', '').split())
        if ip and isp:
            isp = urllib.parse.unquote(isp).replace('+', ' ')
            return (ip, isp)
    except Exception:
        return


def mask_ip(ipaddr):
    ipaddr_s = ipaddress.ip_address(ipaddr)
    if ipaddr_s.version == 4:
        ipaddr_s = ipaddress.ip_interface(ipaddr + '/24')
        return str(ipaddr_s.network).replace('0/24', 'xxx')
    if ipaddr_s.version == 6:
        ipaddr_s = ipaddress.ip_interface(ipaddr + '/64')
        return str(ipaddr_s.network).replace(':/64', 'xxxx::')
    return None


def _dpi_send(host, port, data, fragment_size=0, fragment_count=0):
    sock = socket.create_connection((host, port), 10)
    if fragment_count:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    try:
        for fragment in range(fragment_count):
            sock.sendall(data[:fragment_size].encode())
            data = data[fragment_size:]
        sock.sendall(data.encode())
        recvdata = sock.recv(8192)
        recv = recvdata
        while recvdata:
            recvdata = sock.recv(8192)
            recv += recvdata
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        sock.close()
    return _decode_bytes(recv)


def _dpi_build_tests(host, urn, ip, lookfor):
    dpi_built_list = \
        {'дополнительный пробел после GET':
             {'data': "GET  {} HTTP/1.0\r\n".format(urn) + \
                      "Host: {}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'перенос строки перед GET':
             {'data': "\r\nGET {} HTTP/1.0\r\n".format(urn) + \
                      "Host: {}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'табуляция в конце домена':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Host: {}\t\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'фрагментирование заголовка':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Host: {}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 2, 'fragment_count': 6},
         'точка в конце домена':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Host: {}.\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'заголовок hoSt вместо Host':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "hoSt: {}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'заголовок hOSt вместо Host':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "hOSt: {}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'значение Host БОЛЬШИМИ БУКВАМИ':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Host: {}\r\nConnection: close\r\n\r\n".format(host.upper()),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'отсутствие пробела между двоеточием и значением заголовка Host':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Host:{}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'перенос строки в заголовках в UNIX-стиле':
             {'data': "GET {} HTTP/1.0\n".format(urn) + \
                      "Host: {}\nConnection: close\n\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'необычный порядок заголовков':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Connection: close\r\nHost: {}\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         'фрагментирование заголовка, hoSt и отсутствие пробела одновременно':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "hoSt:{}\r\nConnection: close\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 2, 'fragment_count': 6},
         '7 КБ данных перед Host':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Connection: close\r\n" + \
                      "X-Padding1: {}\r\n".format('1' * 1000) + \
                      "X-Padding2: {}\r\n".format('2' * 1000) + \
                      "X-Padding3: {}\r\n".format('3' * 1000) + \
                      "X-Padding4: {}\r\n".format('4' * 1000) + \
                      "X-Padding5: {}\r\n".format('5' * 1000) + \
                      "X-Padding6: {}\r\n".format('6' * 1000) + \
                      "X-Padding7: {}\r\n".format('7' * 1000) + \
                      "Host: {}\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         '15 КБ данных перед Host':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Connection: close\r\n" + \
                      "X-Padding1: {}\r\n".format('1' * 1000) + \
                      "X-Padding2: {}\r\n".format('2' * 1000) + \
                      "X-Padding3: {}\r\n".format('3' * 1000) + \
                      "X-Padding4: {}\r\n".format('4' * 1000) + \
                      "X-Padding5: {}\r\n".format('5' * 1000) + \
                      "X-Padding6: {}\r\n".format('6' * 1000) + \
                      "X-Padding7: {}\r\n".format('7' * 1000) + \
                      "X-Padding8: {}\r\n".format('8' * 1000) + \
                      "X-Padding9: {}\r\n".format('9' * 1000) + \
                      "X-Padding10: {}\r\n".format('0' * 1000) + \
                      "X-Padding11: {}\r\n".format('1' * 1000) + \
                      "X-Padding12: {}\r\n".format('2' * 1000) + \
                      "X-Padding13: {}\r\n".format('3' * 1000) + \
                      "X-Padding14: {}\r\n".format('4' * 1000) + \
                      "X-Padding15: {}\r\n".format('5' * 1000) + \
                      "Host: {}\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         '21 КБ данных перед Host':
             {'data': "GET {} HTTP/1.0\r\n".format(urn) + \
                      "Connection: close\r\n" + \
                      "X-Padding1: {}\r\n".format('1' * 3000) + \
                      "X-Padding2: {}\r\n".format('2' * 3000) + \
                      "X-Padding3: {}\r\n".format('3' * 3000) + \
                      "X-Padding4: {}\r\n".format('4' * 3000) + \
                      "X-Padding5: {}\r\n".format('5' * 3000) + \
                      "X-Padding6: {}\r\n".format('6' * 3000) + \
                      "X-Padding7: {}\r\n".format('7' * 3000) + \
                      "Host: {}\r\n\r\n".format(host),
              'lookfor': lookfor, 'ip': ip,
              'fragment_size': 0, 'fragment_count': 0},
         }
    return dpi_built_list


def check_isup(page_url):
    """
    Check if the site is up using isup.me or whatever is set in
    `isup_fmt`. Return True if it's up, False if it's not, None
    if isup.me is itself unaccessible or there was an error while
    getting the response.

    `page_url` must be a string and presumed to be sanitized (but
    doesn't have to be the domain and nothing else, isup.me accepts
    full URLs)

    isup.me can't check HTTPS URL yet, so we return True for them.
    It's still useful to call check_isup even on HTTPS URLs for two
    reasons: because we may switch to a service that can can check them
    in the future and because check_isup will output a notification for
    the user.
    """
    # Note that isup.me doesn't use HTTPS and therefore the ISP can slip
    # false information (and if it gets blocked, the error page by the ISP can
    # happen to have the markers we look for). We should inform the user about
    # this possibility when showing results.
    if disable_isup:
        return True
    elif page_url.startswith("https://"):
        # print("[☠] {} не поддерживает HTTPS, считаем, что сайт работает, "
        #      "а проблемы только у нас".format(isup_server))
        return True

    print("\tПроверяем доступность через {}".format(isup_server))

    url = isup_fmt.format(urllib.parse.urlparse(page_url).netloc)
    status, output = _get_url(url)
    # if output:
    #    output = json.loads(output)

    if status in (0, -1):
        print("[⁇] Ошибка при соединении с {}".format(isup_server))
        return None
    elif status != 200:
        print("[⁇] Неожиданный ответ от {}, код {}".format(isup_server, status))
        return None
    elif 'upicon' in output:
        print("[☠] Сайт доступен, проблемы только у нас")
        return True
    elif 'downicon' in output:
        print("[✗] Сайт недоступен, видимо, он не работает")
        return False
    else:
        print("[⁇] Не удалось распознать ответ от {}".format(isup_server))
        return None


DNS_IPV4 = 0
DNS_IPV6 = 1


def test_dns(dnstype=DNS_IPV4):
    sites_list = list(dns_records_list)
    query_type = ("A" if dnstype == DNS_IPV4 else "AAAA")

    print("[O] Тестируем " + ("IPv4" if dnstype == DNS_IPV4 else "IPv6") + " DNS")

    resolved_default_dns = _get_a_records(sites_list, query_type)
    print("\tЧерез системный DNS:\t", str(resolved_default_dns))
    resolved_google_dns = _get_a_records(sites_list, query_type, (google_dns if dnstype == DNS_IPV4 else google_dns_v6))
    if resolved_google_dns:
        print("\tЧерез Google DNS:\t", str(resolved_google_dns))
    else:
        print("\tНе удалось подключиться к Google DNS")
    resolved_google_api = _get_a_records(sites_list, query_type, googleapi=True)
    if resolved_google_api:
        print("\tЧерез Google API:\t", str(resolved_google_api))
    else:
        print("\tНе удалось подключиться к Google API")
        really_bad_fuckup_happened()
    resolved_fake_dns = _get_a_records((sites_list[0],), query_type, (fake_dns if dnstype == DNS_IPV4 else fake_dns_v6))
    if resolved_fake_dns:
        print("\tЧерез недоступный DNS:\t", str(resolved_fake_dns))
    else:
        print("\tНесуществующий DNS не вернул адресов (это не ошибка)")

    if not resolved_default_dns:
        print("[?] Ошибка получения адреса через системный DNS")
        really_bad_fuckup_happened()
        return 5

    elif not resolved_google_dns:
        print("[☠] Сторонние DNS блокируются")
        return 4

    # Assume that Google API always works and returns correct addresses
    dns_records = resolved_google_api

    if not dns_records:
        print("[?] Не удалось связаться с Google API. Проверка DNS сломана.")
        really_bad_fuckup_happened()
        return 5

    if resolved_default_dns == resolved_google_dns:
        if not resolved_fake_dns and len(resolved_default_dns) == len(dns_records):
            print("[✓] DNS-записи не подменяются")
            print("[✓] DNS не перенаправляется")
            return 0

        if resolved_default_dns == dns_records:
            # Resolved DNS = Google DNS = Google API, and fake
            # DNS resolved something.
            print("[✓] DNS-записи не подменяются")
            print("[☠] DNS перенаправляется")
            return 1
        else:
            print("[☠] DNS-записи подменяются")
            print("[☠] DNS перенаправляется")
            return 2

    else:
        if resolved_google_dns == dns_records:
            print("[☠] DNS-записи подменяются")
            print("[✓] DNS не перенаправляется")
            return 3

    if resolved_fake_dns:
        # Resolved DNS != Google DNS != Google API, and fake DNS resolved something.
        print("[☠] DNS-записи подменяются")
        print("[☠] DNS перенаправляется")
        return 2

    print("[?] Способ блокировки DNS определить не удалось. "
          "Убедитесь, что вы используете DNS провайдера, а не сторонний.")
    really_bad_fuckup_happened()
    return 5


HTTP_ACCESS_NOBLOCKS = 0
HTTP_ACCESS_IPBLOCK = 1
HTTP_ACCESS_IPDPI = 2
HTTP_ACCESS_FULLDPI = 3

HTTP_ISUP_ALLUP = 0
HTTP_ISUP_SOMEDOWN = 1
HTTP_ISUP_ALLDOWN = 2
HTTP_ISUP_BROKEN = 3


def test_http_access(by_ip=False):
    """
    Test plain HTTP access and return three values:

    1. The result - one of the HTTP_ACCESS_* constants
    2. isup.me info - one of the HTTP_ISUP_* constants
    3. Subdomain block result
    """
    sites = http_list
    proxy = proxy_addr

    print("[O] Тестируем HTTP" + (' (по настоящим IP-адресам сайтов)' if by_ip else ''))

    successes_v4 = 0
    successes_v6 = 0
    successes_proxy = 0
    down = 0
    blocks = 0
    blocks_ambiguous = 0
    blocks_subdomains = 0

    result_v4 = -1
    result_v6 = -1

    for site in sorted(sites):
        print("\tОткрываем ", site)
        # First try to resolve IP address using Google API.
        # Use a static one if this did not work.
        if by_ip:
            domain = list(urllib.parse.urlsplit(site))[1]
            newip = _get_a_record_over_google_api(domain)
            if ipv6_available:
                newipv6 = _get_a_record_over_google_api(domain, 'AAAA')

            if newip:
                sites[site]['ip'] = newip[0]
            if ipv6_available and sites[site].get('ipv6') and newipv6:
                sites[site]['ipv6'] = '[' + newipv6[0] + ']'

        if ipv6_available:
            result = _get_url(site, ip=sites[site].get('ip'), headers=True,
                              follow_redirects=sites[site].get('follow_redirects', True))
            result_v6 = _get_url(site, ip=sites[site].get('ipv6'), headers=True,
                                 follow_redirects=sites[site].get('follow_redirects', True))
        else:
            result = _get_url(site, ip=sites[site].get('ip') if by_ip else None,
                              headers=True,
                              follow_redirects=sites[site].get('follow_redirects', True))

        result_ok = (result[0] == sites[site]['status'] and result[1].find(sites[site]['lookfor']) != -1)
        if ipv6_available and sites[site].get('ipv6'):
            result_v6_ok = (result_v6[0] == sites[site]['status'] and result_v6[1].find(sites[site]['lookfor']) != -1)
        else:
            result_v6_ok = True  # Not really

        if result_ok and result_v6_ok:
            print("[✓] Сайт открывается")

            if sites[site].get('is_blacklisted', True):
                successes_v4 += 1
                successes_v6 += 1
        elif ipv6_available and (result_ok or result_v6_ok):
            if not result_ok and result_v6_ok:
                print("[!] Сайт открывается только по IPv6")
                successes_v6 += 1
            else:
                print("[!] Сайт открывается только по IPv4")
                successes_v4 += 1
        if not (result_ok and result_v6_ok):
            if (result[0] == sites[site]['status'] or (ipv6_available and result_v6[0] == sites[site]['status'])):
                print("[☠] Получен неожиданный ответ, скорее всего, "
                      "страница-заглушка провайдера. Пробуем через прокси.")
            else:
                print("[☠] Сайт не открывается, пробуем через прокси")
            result_proxy = _get_url(site, proxy)
            if result_proxy[0] == sites[site]['status'] and result_proxy[1].find(sites[site]['lookfor']) != -1:
                print("[✓] Сайт открывается через прокси")
                if sites[site].get('is_blacklisted', True):
                    successes_proxy += 1
            else:
                if result_proxy[0] == sites[site]['status']:
                    print("[☠] Получен неожиданный ответ, скорее всего, "
                          "страница-заглушка провайдера. Считаем заблокированным.")
                else:
                    print("[☠] Сайт не открывается через прокси")
                isup = check_isup(site)
                if isup is None:
                    if sites[site].get('is_blacklisted', True):
                        blocks_ambiguous += 1
                elif isup:
                    if sites[site].get('subdomain'):
                        blocks_subdomains += 1
                    if sites[site].get('is_blacklisted', True):
                        blocks += 1
                else:
                    if sites[site].get('is_blacklisted', True):
                        down += 1

    all_sites = [http_list[i].get('is_blacklisted', True) for i in http_list].count(True)

    # Result without isup.me
    if successes_v4 == all_sites:
        result_v4 = HTTP_ACCESS_NOBLOCKS
    elif successes_v4 > 0 and successes_v4 + successes_proxy == all_sites:
        result_v4 = HTTP_ACCESS_IPDPI
    elif successes_v4 > 0:
        result_v4 = HTTP_ACCESS_FULLDPI
    else:
        result_v4 = HTTP_ACCESS_IPBLOCK

    if ipv6_available:
        if successes_v6 == all_sites:
            result_v6 = HTTP_ACCESS_NOBLOCKS
        elif successes_v6 > 0 and successes_v6 + successes_proxy == all_sites:
            result_v6 = HTTP_ACCESS_IPDPI
        elif successes_v6 > 0:
            result_v6 = HTTP_ACCESS_FULLDPI
        else:
            result_v6 = HTTP_ACCESS_IPBLOCK

    # isup.me info
    if blocks_ambiguous > 0:
        isup = HTTP_ISUP_BROKEN
    elif down == all_sites:
        isup = HTTP_ISUP_ALLDOWN
    elif down > 0:
        isup = HTTP_ISUP_SOMEDOWN
    else:
        isup = HTTP_ISUP_ALLUP

    return result_v4, result_v6, isup, (blocks_subdomains > 0)


def test_https_cert():
    sites = https_list
    isup_problems = False

    print("[O] Тестируем HTTPS")

    siteresults = []
    for site in sorted(sites):
        print("\tОткрываем ", site)
        domain = list(urllib.parse.urlsplit(site))[1]
        newip = _get_a_record_over_google_api(domain)
        if newip:
            newip = newip[0]
            result = _get_url(site, ip=newip, follow_redirects=False)
        else:
            print_debug("Can't resolve IP for", site)
            result = _get_url(site, follow_redirects=False)
        if result[0] == -1:
            print("[☠] Сертификат подменяется")
            siteresults.append(False)
        elif result[0] == 0:
            print("[☠] Сайт не открывается")
            if check_isup(site):
                siteresults.append('no')
            else:
                isup_problems = True
        else:
            print("[✓] Сайт открывается")
            siteresults.append(True)
    if 'no' in siteresults:
        # Blocked
        return 2
    elif False in siteresults:
        # Wrong certificate
        return 1
    elif not isup_problems and all(siteresults):
        # No blocks
        return 0
    else:
        # Some sites are down or unknown result
        return 3


def test_dpi():
    global message_to_print
    message_to_print = ""
    print("[O] Тестируем обход DPI" + (' (только IPv4)' if ipv6_available else ''))

    dpiresults = []
    for dpisite in sorted(dpi_list):
        site = dpi_list[dpisite]
        # First try to resolve IP address using Google API.
        # Use a static one if this did not work.
        newip = _get_a_record_over_google_api(site['host'])
        if newip:
            site['ip'] = newip[0]
        if ipv6_available:
            newip = _get_a_record_over_google_api(site['host'], 'AAAA')
            if newip:
                site['ipv6'] = newip[0]

        dpi_built_tests = _dpi_build_tests(site['host'], site['urn'], site['ip'], site['lookfor'])
        for testname in sorted(dpi_built_tests):
            test = dpi_built_tests[testname]
            print("\tПробуем способ «{}» на {}".format(testname, dpisite))
            try:
                result = _dpi_send(test.get('ip'), 80, test.get('data'), test.get('fragment_size'),
                                   test.get('fragment_count'))
            except (KeyboardInterrupt, SystemExit) as e:
                # re-raise exception to send it to caller function
                raise e
            except Exception as e:
                print("[☠] Ошибка:", repr(e))
            else:
                if result.split("\n")[0].find('200 ') != -1 and result.find(test['lookfor']) != -1:
                    print("[✓] Сайт открывается")
                    dpiresults.append(testname)
                elif result.split("\n")[0].find('200 ') == -1 and result.find(test['lookfor']) != -1:
                    print("[!] Сайт не открывается, обнаружен пассивный DPI!")
                    dpiresults.append('Passive DPI')
                else:
                    print("[☠] Сайт не открывается")
    if web_interface:
        return message_to_print
    return list(set(dpiresults))


def check_ipv6_availability():
    print("Проверка работоспособности IPv6", end='')
    v6addr = _get_a_record("ipv6.icanhazip.com", "AAAA")
    if (v6addr):
        v6 = _get_url("http://ipv6.icanhazip.com/", ip=v6addr[0])
        if len(v6[1]):
            v6src = v6[1].strip()
            if force_ipv6 or (not ipaddress.IPv6Address(v6src).teredo
                              and not ipaddress.IPv6Address(v6src).sixtofour):
                print(": IPv6 доступен!")
                return v6src
            else:
                print(": обнаружен туннель Teredo или 6to4, игнорируем.")
                return False
    print(": IPv6 недоступен.")
    return False


def get_ispinfo(ipaddr):
    try:
        rdap_response = ipwhois.IPWhois(ipaddr)
        ispinfo = rdap_response.lookup_rdap(depth=1)
        return ispinfo['asn']
    except (ipwhois.exceptions.ASNRegistryError,
            ipwhois.exceptions.ASNLookupError,
            ipwhois.exceptions.ASNParseError,
            ipwhois.exceptions.HTTPLookupError,
            ipwhois.exceptions.HTTPRateLimitError):
        return False


def main():
    ipv6_addr = None
    global ipv6_available

    print("BlockCheck v{}".format(VERSION))
    print("Для получения корректных результатов используйте DNS-сервер",
          "провайдера и отключите средства обхода блокировок.")
    print()

    if web_interface:
        return message_to_print

    latest_version = _get_url("https://raw.githubusercontent.com/ValdikSS/blockcheck/master/latest_version.txt")
    if latest_version[0] == 200 and latest_version[1].strip() != VERSION:
        print("Доступная новая версия программы: {}. Обновитесь, пожалуйста.".format(latest_version[1].strip()))
        print()
    if not disable_ipv6:
        ipv6_available = check_ipv6_availability()
        if (ipv6_available):
            ipv6_addr = ipv6_available
    ip_isp = get_ip_and_isp()
    if ip_isp:
        if ipv6_available:
            print("IP: {}, IPv6: {}, провайдер: {}".format(mask_ip(ip_isp[0]), mask_ip(ipv6_addr), ip_isp[1]))
            if not force_ipv6:
                asn4 = get_ispinfo(ip_isp[0])
                asn6 = get_ispinfo(ipv6_addr)
                if asn4 and asn6 and asn4 != asn6:
                    ipv6_available = False
                    print("Вероятно, у вас IPv6-туннель. Проверка IPv6 отключена.")
        else:
            print("IP: {}, провайдер: {}".format(mask_ip(ip_isp[0]), ip_isp[1]))
        print()
    dnsv4 = test_dns(DNS_IPV4)
    dnsv6 = 0
    if ipv6_available:
        print()
        dnsv6 = test_dns(DNS_IPV6)
    print()
    http_v4, http_v6, http_isup, subdomain_blocked = test_http_access((dnsv4 != 0) or (dnsv6 != 0))
    print()
    https = test_https_cert()
    print()
    dpi = '-'
    if http_v4 > 0 or http_v6 > 0 or force_dpi_check:
        dpi = test_dpi()
        print()
    print("[!] Результат:")
    if dnsv4 == 5:
        print("[⚠] Не удалось определить способ блокировки IPv4 DNS.\n",
              "Верните настройки DNS провайдера, если вы используете сторонний DNS-сервер.",
              "Если вы используете DNS провайдера, возможно, ответы DNS модифицирует вышестоящий",
              "провайдер.\n",
              "Вам следует использовать шифрованный канал до DNS-серверов, например, через VPN, Tor, " + \
              "HTTPS/Socks прокси или DNSCrypt.")
    elif dnsv4 == 4:
        print("[⚠] Ваш провайдер блокирует сторонние IPv4 DNS-серверы.\n",
              "Вам следует использовать шифрованный канал до DNS-серверов, например, через VPN, Tor, " + \
              "HTTPS/Socks прокси или DNSCrypt.")
    elif dnsv4 == 3:
        print("[⚠] Ваш провайдер подменяет DNS-записи, но не перенаправляет сторонние IPv4 DNS-серверы на свой.\n",
              "Вам поможет смена DNS, например, на Яндекс.DNS 77.88.8.8 или Google DNS 8.8.8.8 и 8.8.4.4.")
    elif dnsv4 == 2:
        print("[⚠] Ваш провайдер подменяет DNS-записи и перенаправляет сторонние IPv4 DNS-серверы на свой.\n",
              "Вам следует использовать шифрованный канал до DNS-серверов, например, через VPN, Tor, " + \
              "HTTPS/Socks прокси или DNSCrypt.")
    elif dnsv4 == 1:
        print("[⚠] Ваш провайдер перенаправляет сторонние IPv4 DNS-серверы на свой, но не подменяет DNS-записи.\n",
              "Это несколько странно и часто встречается в мобильных сетях.\n",
              "Если вы хотите использовать сторонний DNS, вам следует использовать шифрованный канал до " + \
              "DNS-серверов, например, через VPN, Tor, HTTPS/Socks прокси или DNSCrypt, но обходу " + \
              "блокировок это не поможет.")

    if ipv6_available:
        if dnsv6 == 5:
            print("[⚠] Не удалось определить способ блокировки IPv6 DNS.\n",
                  "Верните настройки DNS провайдера, если вы используете сторонний DNS-сервер.",
                  "Если вы используете DNS провайдера, возможно, ответы DNS модифицирует вышестоящий",
                  "провайдер.\n",
                  "Вам следует использовать шифрованный канал до DNS-серверов, например, через VPN, Tor, " + \
                  "HTTPS/Socks прокси или DNSCrypt.")
        elif dnsv6 == 4:
            print("[⚠] Ваш провайдер блокирует сторонние IPv6 DNS-серверы.\n",
                  "Вам следует использовать шифрованный канал до DNS-серверов, например, через VPN, Tor, " + \
                  "HTTPS/Socks прокси или DNSCrypt.")
        elif dnsv6 == 3:
            print("[⚠] Ваш провайдер подменяет DNS-записи, но не перенаправляет сторонние IPv6 DNS-серверы на свой.\n",
                  "Вам поможет смена DNS, например, на Яндекс.DNS 2a02:6b8::feed:0ff или Google DNS 2001:4860:4860::8888.")
        elif dnsv6 == 2:
            print("[⚠] Ваш провайдер подменяет DNS-записи и перенаправляет сторонние IPv6 DNS-серверы на свой.\n",
                  "Вам следует использовать шифрованный канал до DNS-серверов, например, через VPN, Tor, " + \
                  "HTTPS/Socks прокси или DNSCrypt.")
        elif dnsv6 == 1:
            print("[⚠] Ваш провайдер перенаправляет сторонние IPv6 DNS-серверы на свой, но не подменяет DNS-записи.\n",
                  "Это несколько странно и часто встречается в мобильных сетях.\n",
                  "Если вы хотите использовать сторонний DNS, вам следует использовать шифрованный канал до " + \
                  "DNS-серверов, например, через VPN, Tor, HTTPS/Socks прокси или DNSCrypt, но обходу " + \
                  "блокировок это не поможет.")

    if https == 1:
        print("[⚠] Ваш провайдер подменяет HTTPS-сертификат на свой для сайтов из реестра.")
    elif https == 2:
        print("[⚠] Ваш провайдер полностью блокирует доступ к HTTPS-сайтам из реестра.")
    elif https == 3:
        print("[⚠] Доступ по HTTPS проверить не удалось, повторите тест позже.")

    if subdomain_blocked:
        print("[⚠] Ваш провайдер блокирует поддомены у заблокированного домена.")

    if http_isup == HTTP_ISUP_BROKEN:
        print("[⚠] {0} даёт неожиданные ответы или недоступен. Рекомендуем " \
              "повторить тест, когда он начнёт работать. Возможно, эта " \
              "версия программы устарела. Возможно (но маловероятно), " \
              "что сам {0} уже занесён в чёрный список.".format(isup_server))
    elif http_isup == HTTP_ISUP_ALLDOWN:
        print("[⚠] Согласно {}, все проверяемые сайты сейчас не работают. " \
              "Убедитесь, что вы используете последнюю версию программы, и " \
              "повторите тест позже.".format(isup_server))
    elif http_isup == HTTP_ISUP_SOMEDOWN:
        print("[⚠] Согласно {}, часть проверяемых сайтов сейчас не работает. " \
              "Убедитесь, что вы используете последнюю версию программы, и " \
              "повторите тест позже.".format(isup_server))
    elif http_isup != HTTP_ISUP_ALLUP:
        print("[⚠] ВНУТРЕННЯЯ ОШИБКА ПРОГРАММЫ, http_isup = {}".format(http_isup))

    def print_http_result(symbol, message):
        if http_isup == HTTP_ISUP_ALLUP:
            print("{} {}".format(symbol, message))
        else:
            # ACHTUNG: translating this program into other languages
            # might be tricky. Not into English, though.
            print("{} Если проигнорировать {}, то {}" \
                  .format(symbol, isup_server, message[0].lower() + message[1:]))

    if http_v4 == HTTP_ACCESS_IPBLOCK:
        if (ipv6_available and http_v6 == HTTP_ACCESS_IPBLOCK) or not ipv6_available:
            print_http_result("[⚠]", "Ваш провайдер блокирует по IP-адресу. " \
                                     "Используйте любой способ обхода блокировок.")
        elif ipv6_available and http_v6 != HTTP_ACCESS_IPBLOCK:
            print_http_result("[⚠]", "Ваш провайдер блокирует IPv4-сайты по IP-адресу. " \
                                     "Используйте любой способ обхода блокировок.")
    elif http_v4 == HTTP_ACCESS_FULLDPI:
        if (ipv6_available and http_v6 == HTTP_ACCESS_FULLDPI) or not ipv6_available:
            print_http_result("[⚠]", "У вашего провайдера \"полный\" DPI. Он " \
                                     "отслеживает ссылки даже внутри прокси, " \
                                     "поэтому вам следует использовать любое " \
                                     "шифрованное соединение, например, " \
                                     "VPN или Tor.")
        elif ipv6_available and http_v6 != HTTP_ACCESS_FULLDPI:
            print_http_result("[⚠]", "У вашего провайдера \"полный\" DPI для IPv4. Он " \
                                     "отслеживает ссылки даже внутри прокси, " \
                                     "поэтому вам следует использовать любое " \
                                     "шифрованное соединение, например, " \
                                     "VPN или Tor.")
    elif http_v4 == HTTP_ACCESS_IPDPI:
        if (ipv6_available and http_v6 == HTTP_ACCESS_IPDPI) or not ipv6_available:
            print_http_result("[⚠]", "У вашего провайдера \"обычный\" DPI. " \
                                     "Вам поможет HTTPS/Socks прокси, VPN или Tor.")
        elif ipv6_available and http_v6 != HTTP_ACCESS_IPDPI:
            print_http_result("[⚠]", "У вашего провайдера \"обычный\" DPI для IPv4. " \
                                     "Вам поможет HTTPS/Socks прокси, VPN или Tor.")
    elif http_isup == HTTP_ISUP_ALLUP and http_v4 == HTTP_ACCESS_NOBLOCKS \
            and https == 0:
        print_http_result("[☺]", "Ваш провайдер не блокирует сайты.")



    if not disable_report:
        try:
            report_request = urllib.request.urlopen(
                'http://blockcheck.antizapret.prostovpn.org/postdata.php',
                data=urllib.parse.urlencode({
                    "text": printed_text,
                    "text_debug": printed_text_with_debug if really_bad_fuckup else '',
                }).encode('utf-8')
            )
            if (report_request):
                report_request.close()
        except urllib.error.URLError as e:
            # keep it silent
            pass

        if ip_isp:
            need_help_isp_list = _get_url(
                "https://raw.githubusercontent.com/ValdikSS/blockcheck/master/we_need_your_help_isp_list.txt")
            if need_help_isp_list[0] == 200:
                need_help_isp_list = need_help_isp_list[1]
                for need_help_isp in need_help_isp_list.split("\n"):
                    need_help_isp = need_help_isp.strip().lower()
                    if need_help_isp and need_help_isp in ip_isp[1].lower():
                        print()
                        print("[⚠] Нам нужна ваша помощь!\n",
                              "Пожалуйста, помогите собрать расширенные данные о вашем провайдере:\n",
                              "https://github.com/ValdikSS/blockcheck/wiki/Нужна-ваша-помощь"
                              )


def setup_args():
    if getattr(sys, 'frozen', False):
        os.environ['SSL_CERT_FILE'] = os.path.join(sys._MEIPASS, 'lib', 'ca-certificates.crt')

    parser = argparse.ArgumentParser(description='Определитель типа блокировки сайтов у провайдера.')
    parser.add_argument('--console', action='store_true', help='Консольный режим. Отключает Tkinter GUI.')
    parser.add_argument('--no-report', action='store_true',
                        help='Не отправлять результат на сервер (отправляется только выводимый текст).')
    parser.add_argument('--no-isup', action='store_true',
                        help='Не проверять доступность сайтов через {}.' \
                        .format(isup_server))
    parser.add_argument('--force-dpi-check', action='store_true',
                        help='Выполнить проверку DPI, даже если провайдер не блокирует сайты.')
    parser.add_argument('--disable-ipv6', action='store_true', help='Отключить поддержку IPv6.')
    parser.add_argument('--force-ipv6', action='store_true', help='Игнорировать обнаружение туннелей.')
    parser.add_argument('--debug', action='store_true', help='Включить режим отладки (и --no-report).')
    parser.add_argument('--web', action='store_true', help='Веб-интерфейс.')
    args = parser.parse_args()

    if args.console:
        global tkusable
        tkusable = False

    if args.no_isup:
        global disable_isup
        disable_isup = True

    if args.no_report:
        global disable_report
        disable_report = True

    if args.force_dpi_check:
        global force_dpi_check
        force_dpi_check = True

    if args.disable_ipv6:
        global disable_ipv6
        disable_ipv6 = True

    if args.force_ipv6:
        global force_ipv6
        force_ipv6 = True

    if args.debug:
        global debug
        debug = True
        disable_report = True

    if args.web:
        global web_interface
        web_interface = True

    return 0


if __name__ == "__main__":
    # if getattr(sys, 'frozen', False):
    #     os.environ['SSL_CERT_FILE'] = os.path.join(sys._MEIPASS, 'lib', 'ca-certificates.crt')
    #
    # parser = argparse.ArgumentParser(description='Определитель типа блокировки сайтов у провайдера.')
    # parser.add_argument('--console', action='store_true', help='Консольный режим. Отключает Tkinter GUI.')
    # parser.add_argument('--no-report', action='store_true', help='Не отправлять результат на сервер (отправляется только выводимый текст).')
    # parser.add_argument('--no-isup', action='store_true',
    #                         help='Не проверять доступность сайтов через {}.' \
    #                                 .format(isup_server))
    # parser.add_argument('--force-dpi-check', action='store_true', help='Выполнить проверку DPI, даже если провайдер не блокирует сайты.')
    # parser.add_argument('--disable-ipv6', action='store_true', help='Отключить поддержку IPv6.')
    # parser.add_argument('--force-ipv6', action='store_true', help='Игнорировать обнаружение туннелей.')
    # parser.add_argument('--debug', action='store_true', help='Включить режим отладки (и --no-report).')
    # parser.add_argument('--web', action='store_true', help='Веб-интерфейс.')
    # args = parser.parse_args()
    #
    # if args.console:
    #     tkusable = False
    #
    # if args.no_isup:
    #     disable_isup = True
    #
    # if args.no_report:
    #     disable_report = True
    #
    # if args.force_dpi_check:
    #     force_dpi_check = True
    #
    # if args.disable_ipv6:
    #     disable_ipv6 = True
    #
    # if args.force_ipv6:
    #     force_ipv6 = True
    #
    # if args.debug:
    #     debug = True
    #     disable_report = True
    #
    # if args.web:
    #     web_interface = True

    setup_args()

    if tkusable:
        root = tk.Tk()
        root.title("BlockCheck")
        root.protocol("WM_DELETE_WINDOW", tk_terminate)
        text = ThreadSafeConsole(root, wrap=tk.WORD)
        text.pack(expand=1, fill='both')
        threading.Thread(target=main).start()
        try:
            root.mainloop()
        except (KeyboardInterrupt, SystemExit):
            os._exit(0)
    else:

        try:
            main()
        except (KeyboardInterrupt, SystemExit):
            sys.exit(1)

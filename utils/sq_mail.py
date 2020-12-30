# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import platform
import os
import argparse
import time
import traceback
import smtplib
from email.mime.text import MIMEText
from email.header import Header


def sendmail(mailserver, sender, password, receivers, subject, content):
    smtp = smtplib.SMTP_SSL(mailserver, port=465)
    smtp.login(sender, password)
    for r in receivers:
        mime = MIMEText(content, 'plain', 'utf-8')
        mime['Date'] = time.ctime()
        mime['From'] = str(Header("Sunquant", 'utf-8')) + " <" + sender + ">"
        mime['To'] = str(Header(r.split('@')[0], 'utf-8')) + ' <' + r + '>'
        mime['Subject'] = Header(subject, 'utf-8')
        smtp.sendmail(sender, r, mime.as_string())
    smtp.quit()
    #except smtplib.SMTPException as e:
    return True

if __name__ == '__main__':
    if platform.system() == "Linux":
        cmdLineParser = argparse.ArgumentParser("sq_mail")
        cmdLineParser.description = "send mail which including the result of defined command"
        cmdLineParser.add_argument("-m", "--mailserver", type=str, default=None, help="mail server")
        cmdLineParser.add_argument("-s", "--sender", type=str, default=None, help="sender")
        cmdLineParser.add_argument("-p", "--password", type=str, default=None, help="password")
        cmdLineParser.add_argument("-r", "--receiver", type=str, default=None, help="receiver")
        cmdLineParser.add_argument("-c", "--command", type=str, default=None, help="command")
        args = cmdLineParser.parse_args()
        print("sq_mail,using args", args)

        if args.receiver and args.command:
            content = "\n" + args.command + " 运行结果:\n"
            report1 = os.popen(args.command)
            content += report1.read()
            sendmail(args.mailserver, args.sender, args.password, args.receiver.split(','), "Sunquant 每日Check ", content)
        else:
            print("\n\tNo receiver and command defined.\n")

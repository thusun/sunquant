# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import platform
import os
import sys
import datetime
import logging
from logging.handlers import TimedRotatingFileHandler
import pandas
from utils.sq_setting import *


__LogPathName__ = "sunquant"


if hasattr(sys, '_getframe'):
    currentframe = lambda: sys._getframe(3)
else:  # pragma: no cover
    def currentframe():
        """Return the frame object for the caller's stack frame."""
        try:
            raise Exception
        except Exception:
            return sys.exc_info()[2].tb_frame.f_back


class SQLog(object):

    _level_dict = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARN,
        "error": logging.ERROR,
        "critical": logging.CRITICAL
    }

    _default_instance = None

    def __init__(self, dirname='unknown-market', filename='unknown-strategy', console_log_level='info', file_log_level='info', is_console=1, is_file=1):
        self.ConsoleLogLevel = console_log_level
        self.FileLogLevel = file_log_level
        self.IsConsole = is_console
        self.IsFile = is_file

        self.log_filepath = None

        self.__init_log_engine(dirname, filename, self.ConsoleLogLevel, self.FileLogLevel, self.IsConsole, self.IsFile)

    @classmethod
    def instance(cls):
        if cls._default_instance is None:
            cls._default_instance = SQLog()
        return cls._default_instance

    @classmethod
    def debug(cls, *args):
        cls.instance().log('debug', *args)

    @classmethod
    def info(cls, *args):
        cls.instance().log('info', *args)

    @classmethod
    def warn(cls, *args):
        cls.instance().log('warn', *args)

    @classmethod
    def error(cls, *args):
        cls.instance().log('error', *args)

    @classmethod
    def critical(cls, *args):
        cls.instance().log('critical', *args)

    def log(self, loglevel, *args):
        level = self._level_dict.get(loglevel, logging.INFO)
        self._logger.log(level, self.__to_string(*args))

    def get_logfilepath(self):
        return self.log_filepath

    @classmethod
    def setup_root_logger(cls, dirname, filename, console_log_level='info', file_log_level='info', is_console=1, is_file=1):
        rootlogger = logging.getLogger()
        if rootlogger.hasHandlers():
            for hdlr in rootlogger.handlers.copy():
                rootlogger.removeHandler(hdlr)

        formatter = logging.Formatter('%(asctime)s  %(levelname)s: %(message)s')
        if platform.system() == "Windows":
            log_dir = os.path.join(os.getenv("appdata"), __LogPathName__, dirname)
        else:
            log_dir = os.path.join(os.environ['HOME'], __LogPathName__, dirname)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        rootlogger.setLevel(logging.DEBUG)

        if is_console:
            consoleHandler = logging.StreamHandler()
            consoleHandler.setLevel(cls._level_dict.get(console_log_level))
            consoleHandler.setFormatter(formatter)
            rootlogger.addHandler(consoleHandler)

        if is_file:
            rootlog_filepath = os.path.join(log_dir, filename + '.log')
            fileHandler = TimedRotatingFileHandler(rootlog_filepath, when='midnight', interval=1, encoding="utf-8", backupCount=3)
            fileHandler.setLevel(cls._level_dict.get(file_log_level))
            fileHandler.setFormatter(formatter)
            rootlogger.addHandler(fileHandler)
            print("SQLog:----------RootLogFile----------:" + rootlog_filepath, flush=True)

    @classmethod
    def init_default(cls, dirname, filename, console_log_level='info', file_log_level='info', is_console=1, is_file=1):
        cls._default_instance = SQLog(dirname, filename, console_log_level, file_log_level, is_console, is_file)

    def __init_log_engine(self, dirname, filename, console_log_level, file_log_level, is_console, is_file):
        self._logger = logging.getLogger(dirname+"_"+filename)
        if self._logger.hasHandlers():
            for hdlr in self._logger.handlers.copy():
                self._logger.removeHandler(hdlr)

        formatter = logging.Formatter('%(asctime)s  %(levelname)s: %(message)s')
        if platform.system() == "Windows":
            log_dir = os.path.join(os.getenv("appdata"), __LogPathName__, dirname)
        else:
            log_dir = os.path.join(os.environ['HOME'], __LogPathName__, dirname)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        self._logger.setLevel(logging.DEBUG)

        if is_console:
            consoleHandler = logging.StreamHandler()
            consoleHandler.setLevel(self._level_dict.get(console_log_level))
            consoleHandler.setFormatter(formatter)
            self._logger.addHandler(consoleHandler)

        if is_file:
            self.log_filepath = os.path.join(log_dir, filename + '.log')
            fileHandler = TimedRotatingFileHandler(self.log_filepath, when='W6', interval=1, encoding="utf-8")
            fileHandler.setLevel(self._level_dict.get(file_log_level))
            fileHandler.setFormatter(formatter)
            self._logger.addHandler(fileHandler)
            print("SQLog:----------LogFile----------:" + self.log_filepath, flush=True)

    def __find_caller(self):
        """
        Find the stack frame of the caller so that we can note the source
        file name, line number and function name.
        """
        f = currentframe()
        #On some versions of IronPython, currentframe() returns None if
        #IronPython isn't run with -X:Frames.
        if f is not None:
            f = f.f_back
        rv = "(unknown file)", 0, "(unknown function)", None
        while hasattr(f, "f_code"):
            co = f.f_code
            filename = os.path.normcase(co.co_filename)
            srcfile = os.path.normcase(self.error.__code__.co_filename)
            if filename == srcfile:
                f = f.f_back
                continue
            rv = (co.co_filename, f.f_lineno, co.co_name)
            break
        return rv

    def __format_msg(self, msg):
        rv = self.__find_caller()
        if (rv is not None) and (len(rv) > 2):
            filepath = rv[0]
            [_, filename] = os.path.split(filepath)
            return "[{}] {}:{}: ".format(filename, rv[2], rv[1]) + msg
        else:
            return msg

    def __to_string(self, *args):
        s = ""
        iss_last = False
        for v in args:
            if isinstance(v, str) and not iss_last:
                s = s + " " + v
                iss_last = True
            elif isinstance(v, float):
                if v > 100:
                    v = round(v, 2)
                elif v > 1:
                    v = round(v, 4)
                else:
                    v = round(v, 6)
                s = s + str(v) + " "
                iss_last = False
            elif isinstance(v, pandas.DataFrame):
                s = s + " " + v.to_string()
                iss_last = False
            else:
                s = s + str(v) + " "
                iss_last = False
        return self.__format_msg(s)



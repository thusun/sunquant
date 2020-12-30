# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import os
import platform
import json


__SettingFilename__ = 'setting.json'
__SaveDataPathName__ = "sunquant"


class SQSetting(object):

    _default_instance = None

    def __init__(self):
        self._global_settings = {}
        self._setting_filepath = None
        self.__load_setting()

    @classmethod
    def instance(cls):
        if cls._default_instance is None:
            cls._default_instance = SQSetting()
        return cls._default_instance

    @classmethod
    def global_settings(cls):
        return cls.instance()._global_settings

    @classmethod
    def part_settings(cls, partname):
        if cls.instance()._global_settings is None or partname not in cls.instance()._global_settings:
            raise Exception("setting.json - no "+partname+" config!")
        return cls.instance()._global_settings[partname]

    @classmethod
    def fill_dict_from_settings(cls, dict, partname):
        settings = cls.part_settings(partname)
        for key in dict.keys():
            if key in settings.keys():
                dict[key] = settings[key]
        return True

    @classmethod
    def get_savedata_dir(cls, marketname):
        if marketname is None:
            marketname = ""
        if platform.system() == "Windows":
            sd_path = os.path.join(os.getenv("appdata"), __SaveDataPathName__, marketname)
        else:
            sd_path = os.path.join(os.environ['HOME'], __SaveDataPathName__, marketname)
        if not os.path.exists(sd_path):
            os.makedirs(sd_path)
        return sd_path

    def get_setting_filepath(self):
        if self._setting_filepath is None:
            currentFolder = os.getcwd()
            currentJsonPath = os.path.join(currentFolder, __SettingFilename__)
            if os.path.isfile(currentJsonPath):
                print("SQSeting:----------using current path----------:" + currentJsonPath, flush=True)
                self._setting_filepath = currentJsonPath
            else:
                moduleFolder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                moduleJsonPath = os.path.join(moduleFolder, __SettingFilename__)
                if os.path.isfile(moduleJsonPath):
                    print("SQSeting:----------using module path----------:" + moduleJsonPath, flush=True)
                    self._setting_filepath = moduleJsonPath
                else:
                    sd_path = SQSetting.get_savedata_dir(None)
                    settingJsonPath = os.path.join(sd_path, __SettingFilename__)
                    print("SQSeting:----------using sunquant path----------:" + settingJsonPath, flush=True)
                    self._setting_filepath = settingJsonPath
        return self._setting_filepath

    def __load_setting(self):
        filepath = self.get_setting_filepath()
        with open(filepath, 'rb') as f:
            df = f.read()
            f.close()
            if type(df) is not str:
                df = str(df, encoding='utf-8')
            self._global_settings = json.loads(df)
            return True


class SQSaveData(object):
    _savedata_filepath = None
    _quote_filepath = None

    def __init__(self):
        return

    @classmethod
    def __get_savedata_filepath(cls, marketname, strategyname):
        if cls._savedata_filepath is None:
            sd_path = SQSetting.get_savedata_dir(marketname)
            filepath = os.path.join(sd_path, strategyname+".json")
            print("SQSaveData:----------filepath----------:" + filepath, flush=True)
            cls._savedata_filepath = filepath
        return cls._savedata_filepath

    @classmethod
    def load_data(cls, marketname, strategyname):
        filepath = cls.__get_savedata_filepath(marketname, strategyname)
        if not os.path.exists(filepath):
            return {}
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            f.close()
            return data

    @classmethod
    def save_data(cls, marketname, strategyname, data):
        filepath = cls.__get_savedata_filepath(marketname, strategyname)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.close()
            return True

    @classmethod
    def __get_quote_filepath(cls):
        if cls._quote_filepath is None:
            if platform.system() == "Windows":
                sd_path = os.getenv("appdata")
            else:
                sd_path = "/tmp"
            filepath = os.path.join(sd_path, "stkquote.json")
            print("SQSaveData:----------quotefilepath----------:" + filepath, flush=True)
            cls._quote_filepath = filepath
        return cls._quote_filepath

    @classmethod
    def load_quote_data(cls):
        filepath = cls.__get_quote_filepath()
        if not os.path.exists(filepath):
            return {}
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            f.close()
            return data

    @classmethod
    def save_quote_data(cls, data):
        filepath = cls.__get_quote_filepath()
        alreadyexists = os.path.exists(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.close()
            if not alreadyexists:
                os.chmod(filepath, 0o666)
            return True

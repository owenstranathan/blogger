import os
from pathlib import Path
from appdirs import user_data_dir

APPNAME = "blogger"
AUTHOR = "wabisoft"
APPDATA_LOCAL = Path(user_data_dir(appname=APPNAME, appauthor=AUTHOR))
APPDATA_ROAMING = Path(user_data_dir(appname=APPNAME, appauthor=AUTHOR, roaming=True))
PATHSEP = os.path.sep

if __name__ == "__main__":
    print(APPDATA_ROAMING)

# sunquant

   Python量化框架；
   网格交易；
   杠杆加强的香农网格交易；

   免责声明：请在理解本程序的功能细节后再使用本程序交易，使用本程序交易造成的任何意想不到的损失，原作者概不负责。
   作者邮箱：szy@tsinghua.org.cn  九天
   Sunquant交流QQ群： 957193023


（零）前言

    (1). 本程序香农网格的杠杆加强算法，属于本人独创，更详细的说明，请参见单独的文档《Shannon's Demon with Leverage》。

    (2). 程序启动，参见目录shell_sample\中的脚本start.sh。
        交易引擎trade_engine_xxx作为启动主程序，通过命令行指定 $market（交易的市场） 和 $strategy（使用的策略：shannon或grid）。
        程序的日志文件保存在 ~/sunquant/$market/ 目录下，如果是win10系统，则在 C:\Users\xxx\AppData\Roaming\sunquant\$market。

        对于Futu，需要启动交易网关FutuOpenD，具体参见下面（二）。
        对于IB，需要启动交易网关TWS或者ibgateway，具体参见下面（三）。

    (3). 参数配置，参见setting.json中的注释。
        程序启动后，会按如下次序寻找setting.json配置文件。
        1. 当前目录。
        2. 模块所在目录，即tradeengine目录的上一级目录，也就是源码中setting-sample.json所在的目录。
        3. ~/sunquant/$market （For linux）或者 C:\Users\xxx\AppData\Roaming\sunquant\$market（For win10）

    (4). 程序框架

        1. 交易引擎trade_engine_xxx 初始化，并关联sunquant_frame和启动sunquant_frame。
           启动时，通过参数指定策略：网格'grid' 或者 香农网格'shannon'。

        2. sunquant_frame 创建策略strategy_xxx对象，并调用strategy的init方法初始化策略。

        3. sunquant_frame 每LoopInterval秒，查询一次最新行情数据，并调用strategy的begin_transact方法，
           该方法返回需要挂单的买卖价格及数量信息，sunquant_frame根据该信息，调用trade_engine_xxx下单。

    (5). 收益特性
        1. 对上涨趋势的股票应用该策略，最终会赚得少（与一直持有相比）。

        2. 对下跌趋势的股票应用该策略，最终会赔得少（与一直持有相比）。

        3. 对横盘整理的股票应用该策略，最终会赚得多（与一直持有相比）。

        4. 总体上会平滑收益，并且在长期高位震荡时，也可以实现盈利。

        5. 该策略属于永久有效的策略。只要市场有波动，该策略就有效。

    (6). 支持的交易引擎。

        1. 支持富途证券交易接口Futu（港美股推荐）；

        2. IB交易接口（复杂不稳定）；

        3. 比特币OKEx交易接口；

        4. 比特币Binance交易接口；
        港股和美股交易，推荐使用富途证券交易接口，IB接口复杂不稳定且需要图形界面系统（这有点麻烦）运行网关程序，并且这个
        网关程序，每周需要手动登录一次。


（一）Python开发环境安装

    (1). 安装Anaconda Python 3.7： https://www.anaconda.com/download/

    (2). 安装PyCharm：             https://www.jetbrains.com/pycharm/download/


（二）富途API环境安装

    (1). 富途接口文档              https://openapi.futunn.com/futu-api-doc/

    (2). 安装futu-api：            pip install futu-api
        或者下载 https://github.com/FutunnOpen/py-futu-api 后执行 pip install .

    (3). 安装FutuOpenD，富途接口服务程序
         https://www.futunn.com/download

    (4). 安装C/C++版TA-Lib （ sunquant-master 中的策略并不需要安装此库 ）
        TA-Lib依赖于C/C++版TA-Lib：http://ta-lib.org/hdr_dw.html
        对Linux下载后执行 ./configure --prefix=/usr ; make ; make install； 依赖gcc，yum install gcc; yum install gcc-C++
        对windows，下载解压至C:\ta-lib，如果编译困难，可以直接下载binary包：https://www.lfd.uci.edu/~gohlke/pythonlibs/ 然后 pip install TA_Lib-0.4.9-cp27-none-win_amd64.whl

    (5). 安装python的TA-Lib： （ sunquant-master 中的策略并不需要安装此库 ）
           pip install TA-Lib
        或者下载：                 https://github.com/mrjbq7/ta-lib 后执行 pip install . 或者 python setup.py install
        python的TA-Lib，只是对C/C++版的TA-Lib的包装，需先安装C/C++版TA-Lib

（三）IB API环境安装

    (1). IB接口文档              https://www.interactivebrokers.com

    (2). 安装ibapi：             pip install ibapi

    (3). 安装IB GateWay（仅接入API）或者TWS（界面丰富），IB接口网关服务程序下载：
        https://www.interactivebrokers.com

    (4). ibgateway运行需要Linux桌面系统。
        理想情况，执行下列步骤1和步骤2即可完成管理ibgateway，但是步骤2 运行ibgateway显示不正常，可以用步骤3或者步骤4代替步骤2。

        1. CentOS7版本的可视化界面安装过程如下：
            安装X(X Window System),命令为：
                yum groupinstall "X Window System"（注意有引号）
            安装需要的图形界面软件，xfce，命令为：
                yum groupinstall Xfce
            设置默认通过桌面环境启动服务器的命令为：
                systemctl set-default graphical.target

        2. 远程登录xrdp安装：
            1). 默认库不包含xrdp，需要安装：
                yum install epel-release
                yum install xrdp （此时已默认安装微型tigervnc）
            启动xrdp服务，并设置为开机启动
                systemctl start xrdp
                systemctl enable xrdp
            登录用户需要设置密码登录。运行 passwd 命令设定用户密码。
            接下来就像windows远程桌面连接一样，直接mstsc输入ip，输入用户名/密码，OK，进入。

            2). xrdp 在 ~/.xsession 文件中指定运行的X session。
                .xsession文件内容如下(其中exec后的内容与/usr/share/xsessions/中各session的配置中Exec项相同)：
                    exec startxfce4
                .xsession文件需要有可执行属性 chmod +x .xsession

            3). IB软件在通过xrdp登录后，运行无法正常显示界面，此时可以配置xrdp使用vnc-any
                把/etc/xrdp/xrdp.ini 中的 vnc-any 项的注释#去掉。重启xrdp。
                同时配置步骤3中的"tigervnc配置"，xrdp登录时输入tigervnc的相关参数，进行登录。

            4). xrdp登录某用户时，如果该用户安装了conda，则conda在.bashrc中的初始化操作会毁掉dbus，导致启动xsession不成功，因此
                需要停用conda在.bashrc中的启动脚本。

        3. tigervnc 配置
            windows端VNC viewer官网下载： https://www.realvnc.com
            Liunx端安装VNC Server软件： yum install tigervnc-server
            1). 运行 vncserver 初始化，并设置密码，如果有以前安装的残留，则删除用户目录下的 .vnc 目录及 .Xauthority 文件。
            2). 检查 ~/.vnc/xstart 是否自动关闭了，可以将 vncserver -kill 这一行注释掉。
                如果想用户注销后自动关闭并重启 vncserver，则加入：
                    vncserver -kill $DISPLAY （执行时xstart被kill，后续指令不会被执行，下同）
                    或 systemctl restart vncserver@${DISPLAY}.service （注意非root用户无权限执行）
                    或 sudo /usr/bin/systemctl restart vncserver@:1.service
                    （需配置 visudu: <USER>      <HOSTNAME>=(root)   NOPASSWD: /usr/bin/systemctl restart vncserver@\:1.service
            3). 如果要运行指定的桌面如 xfce，则在 ~/.Xclients 文件中加入 exec startxfce4，并将 .Xclients设为可执行属性。

            4). cp /lib/systemd/system/vncserver@.service /etc/systemd/system/vncserver@:1.service
            5). Copy this file to /etc/systemd/system/vncserver@:1.service
                Replace <USER> with the actual user name and edit vncserver
                parameters appropriately, if root, NOTICE /home/<USER>
                (ExecStart=/usr/sbin/runuser -l <USER> -c "/usr/bin/vncserver %i"
                 PIDFile=/home/<USER>/.vnc/%H%i.pid)

                如果用普通用户启动Xvnc，则需要改成下面这样：
                    ExecStartPre=/usr/sbin/runuser -l <USER> -s /bin/sh -c '/usr/bin/vncserver -kill %i > /dev/null 2>&1 || :'
                    ExecStart=/usr/sbin/runuser -l <USER> -c "/usr/bin/vncserver %i"
                    PIDFile=/home/<USER>/.vnc/%H%i.pid
                    ExecStop=/usr/sbin/runuser -l <USER> -s /bin/sh -c '/usr/bin/vncserver -kill %i > /dev/null 2>&1 || :'
                    或者：
                    User=<USER>
                    Group=<GROUP>
                    ExecStart=/usr/bin/vncserver %i
                    PIDFile=/home/<USER>/.vnc/%H%i.pid
                    ExecStop=/usr/bin/vncserver -kill %i > /dev/null 2>&1
            6). Run `systemctl daemon-reload`
            7). Run `systemctl enable vncserver@:1.service`
            8). Run `systemctl start vncserver@:1.service`

        4. 也可以使用阿里云的远程登录功能来启动ibgateway。

        5. 也可以使用Windows的Xming来模拟XServer（但是在Xming退出时，ibgateway也退出了）：
            windows安装 Xming
            Linux配置/etc/ssh/sshd_config：  X11Forwarding yes
            ssh -X xxx.xxx.xxx.xxx 或者 putty 登录（Enable XForwarding）
            然后运行：
            /root/Jts/ibgateway/978/ibgateway

        6. 也可以指定X Server：
            启动自己的X Server：
            xinit /root/Jts/ibgateway/978/ibgateway -- /usr/bin/openbox :1.0

            或者指定到某个已经存在的X Server：
            XServer端：xinit -- :1.0
            XServer端：xhost + xxx.xxx.xxx.xxx
            XClient端：export DISPLAY=:1.0
            XClient端：/root/Jts/ibgateway/978/ibgateway

    (5). IB TWS设置。
        1. Configuration => Lock and Exit => Set Auto Restart Time
        2. Sound Manager => Non Voice
        2.  API => Settings => Enable ActiveX and Socket Clients, checked
            API => Settings => Read-Only API, unchecked
            API => Settings => Send API Messages in English, checked
            API => Settings => Socket port
            API => Precautions => checked all
        3.  Presets => Stock => Allow order to be routed and executed during pre-open session(if available), checked
            Presets => Stock => Use price management algo, checked
        4.  subscribe Market Data in Mobile IBKR APP: More => Account Management => Market Data Permissions:
            First, change the "Market Data subscriber's Status" to "unprofessional", otherwise, it's expensive.
            then, subscribe the "US Securities Snapshot and Futures Value Bundle" and "US Equity and Options Add-On Streaming Bundle", as a total, $14.5/month
        5. 增加一个新的使用者用户，用于API交易登录。
            账户设置 => 使用者设置 => 新增使用者，添加完毕后，一定要用新增的使用者用户登录一次，设置相关选项，然后等待审批，一般一个工作日审批完成。

（四）OKEx.me API SDK

    (1).  git clone https://github.com/okex/V3-Open-API-SDK.git

（五）binance.com API SDK

    (1).  git clone https://github.com/binance-exchange/python-binance.git


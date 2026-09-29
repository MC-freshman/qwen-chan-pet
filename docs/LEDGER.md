# 缺陷台账（qwen娘）

判据在方案定稿时冻结；执行中发现的问题登记于此，不当场修（越界处置需写明理由）。
方案：`E:\桌宠\docs\改进方案-P表.md`。

| 编号 | 现象 | 复现 | 影响面 | 定位 | 建议处置 |
|---|---|---|---|---|---|
| DQ-1 | Q0 前没有无头自检闸门：数值/台词/存档/日记的正确性只靠肉眼 | 任意改动后无法回归 | 回归安全网 | — | **已补（Q0）**：新建 `app/selftest.py`，8 项检查全绿（out/selftest.json）。首轮误报 4 项（VARS 漏 gap_hour、running-left/right 需 split 折叠、日记需种子数据、窗口阈值过严）均为测试侧问题，台词与数值代码零缺陷 |
| DQ-2 | `state/shy\|annoyed\|dizzy` 三组台词实际不可达：反应态强制 0.9-1.6s < 发言间隔 240s | context_line 的 state 分支（pet.pyw:789）| 21 句准死代码 | 反应时长与频控的量纲不匹配 | 进 Q2：反应台词走独立通道，或反应态延长 |
| DQ-3 | 台词防重复仅靠全局 12 条历史；157 句池子几天后必重复（README 自认） | speech.py:32 + needs.py:150 | 长期观感 | 无分类级冷却 | 进 Q2：扩池 + 分类级冷却 |
| DQ-2 | ~~state/shy\|annoyed\|dizzy 准死角~~ | — | — | — | **已销账（Q2）**：反应态改走独立台词通道（react() 直接说 state/<名>，不受 240s 频控），21 句全部可达 |
| DQ-3 | ~~防重复仅 12 条历史~~ | — | — | — | **已销账（Q2）**：历史 12→40 + 环境类子键 4h 分类级冷却 + 台词 157→273；selftest H 项模拟 7 天发言，48h 窗口重复率 0%（判据 ≤15%） |
| DQ-4 | Q5 微动作与周记 | probe_q5.py | — | — | **已落地（Q5）**：东张西望（三连扫视，4-8min 一次）与伸懒腰（躯干带缓伸 2%，6-10min 一次）进生命层，零新立绘（rigor.LifeLayer）；周记走快照差值法（累计数直接相加会算错），周一自动结上周的账。探针 6/6 绿（out/q5.json） |
| DQ-5 | selftest 的 save 档跨运行残留 40 条历史，把 C 项池子全挡住假红 | Q2 首跑 selftest | 闸门可信度 | Life 复用持久档 | **已修（Q2）**：selftest 开头清理自检档 |
| DQ-6 | `in_span` 空列表崩溃的同类问题在 qwen娘 不存在（quiet_hours 由 in_quiet_hours 处理，空列表语义=不静音 ✓），仅 grok娘 侧有（D-35） | — | — | — | 备注：跨项目语义对齐已完成 |

## 逐行审计轮（9-29）

判据：`python out/probe_audit.py`（29 项，全绿）+ `python out/live_check.py`（真实跑 20s：她在动、日志零新增）
+ `python app/selftest.py`（9/9）+ `python build_motion.py --check`（232 帧全合格）。

| 编号 | 现象 | 复现 | 影响面 | 定位 | 处置 |
|---|---|---|---|---|---|
| DA-1 | 一句 `needs/low_energy` 的 4h 子键冷却能把**整条台词链**静音 4 小时：命中分支直接 `return pick(...)`，而 pick 在冷却内返回 None | `context_line` 连调三次，第二次旧版返回 None（探针 B1-B3） | 她可以几小时不开口，而当时 greet/sense/self 的池子是满的 | pet.pyw `context_line` | **已修**：改成优先级阶梯，试到第一条真拿到词为止。selftest 的 H 项一直按这个语义建模，实现却漏了 |
| DA-2 | 点菜单"退出"后 `TclError: can't invoke "tk" command: application has been destroyed` | run/pet.err.log 实录（旧行号 1132） | 退出路径抛异常、日志被 traceback 污染 | pet.pyw `on_menu`/`refresh_menu` | **已修**：`self.quitting` 早退 + `tk.TclError` 兜底（探针 E1-E2） |
| DA-3 | rig.json 缺某态地标时生命层每帧抛 `TypeError`，而 loop 只把异常写进日志 → 她**定格**而不是崩掉 | `set_landmarks(None, None)` 后调 `offsets()`，t+0.15s 抛错（探针 C1） | 潜在：12 个态今天都有地标 | rigor.py `offsets`（`_turn` 有 `chin_row is None` 守卫，`_glance_turn` 没有） | **已修**：无地标时整段跳过头部动作，摆头/呼吸/眨眼照常（探针 C2 证明没被顺手关掉） |
| DA-4 | `render()` 在动手形变**之前**就登记 live 缓存键：那一帧若抛错，之后每次都命中"还是这一帧"，永久返回旧图且不再抛第二次 | 代码路径推导（与 DA-3 串起来就是"静默定格"的完整链条） | 停摆难以归因 | pet.pyw `render` | **已修**：画成功才登记缓存键 |
| DA-5 | `tts_rate` 写成非整数（如 "fast"）时 `int()` 抛在 `Pet.__init__`，窗口还没建 → 启动即崩；tts.py 里音色/rate 与引擎初始化共用一个 try，一次抛错把 engine 置 None → **永久静音** | 探针 G1：`rate="fast"` 下旧版静音，新版 `last_error="rate set: ..."` 但 194ms 后照样合成 | 一个手改配置能让整只宠物不起来或从此不说话 | pet.pyw `__init__` + tts.py `_loop` | **已修**：配置读非法值按 0；音色与语速各自兜错、失败退回 SAPI 默认音色 |
| DA-6 | `SIGNALS_DIR = ROOT if (ROOT := None) else Path(__file__)...parent.parent/"signals"` —— 表达式本身是死的（还把模块级 `ROOT` 污染成 None），且算出来是 `E:\桌宠\qwen娘\signals`，而 hook 写在 `E:\桌宠\signals` | 探针 A1-A2：那个目录不存在；`E:\桌宠\signals\qoder.busy` 每几分钟就被 Qoder hook 刷新一次，她一个都没读过 | Q3 的 agent 信号功能整体失效 | pet.pyw:64 | **已修**：`APP.parent.parent/"signals"`，与 grok娘 的 `ROOT.parent/"signals"` 和 README 一致（探针 A4 端到端：写文件→她说出来→说到才删） |
| DA-7 | `SIGNAL_KINDS` 少了 `boss`，而 hook_writer 的合法 kind 恰是三个（qoder.busy/qoder.done/boss） | 对照 signals/hook_writer.py 的 assert 列表 | boss 信号被静默丢弃、文件永不消费 | pet.pyw `SIGNAL_KINDS` | **已修**：补进协议表（探针 A5） |
| DA-8 | 点击分区拿**未形变**的底图判命中：缓存命中路径 `self.current = resident.frames[i]`，而画出去那张是视线剪切过的 | 探针 D1-D2：底图不透明、剪影透明的点，旧版判成"碰到她" | 视线偏 3 档时她身上错开 ~5px，戳发梢会戳到空气 | pet.pyw `render`/`zone_at` | **已修**：画片缓存同键存一张 L 剪影（每键 +w*h 字节，仍按 PHOTO_BYTES_PER_STATE 计账），`zone_at` 按画出去那张判 |
| DA-9 | 甩掷判据用 `self.moved > 60`，而 `moved` 数的是 `<B1-Motion>` **事件个数**不是像素：一次 0.2s 的快甩只够 20-30 个事件 | 读 on_drag/on_release；探针 F1 给出快甩的合速度确实 >1500px/s | "把她甩出去"实际上甩不出去 | pet.pyw `on_drag`/`on_release` | **已修**：新增按像素累加的 `moved_px` 并只改这一处判据（拖动/长按判据保持原样，避免连坐） |
| DA-10 | 哨兵无崩溃退避：她若启动即抛（素材缺失、配置错），每 3 秒重拉一次、永远拉不起来，日志只剩一堵重复 traceback | 探针 H：同一场景旧逻辑 200 次轮询拉 200 次，新逻辑只拉 10 次，间隔 3→6→12→…→192s | 一次配置错=后台无限重启 | sentinel.pyw `main` | **已修**：按"这一串连续失败"的起点计 8s 判据 + 指数退避（上限 300s，之后每 5 分钟仍再试）；Qoder 新会话时退避与 quit 标记一起作废 |
| DA-11 | `window_is_borderless_fullscreen` 用 `GetSystemMetrics(0/1)`（只有主屏）：游戏放副屏、铺满副屏也不会触发让路 | 探针 I1：本机她所在屏 1463x823（≠主屏尺寸） | CS2 那类全屏冲突换个显示器就复发 | winutil.py | **已修**：改用 `MonitorFromWindow`+`GetMonitorInfoW` 的所在显示器区域，取不到才退回主屏 |
| DA-12 | `main()` 硬要求 `app/assets/spritesheet.webp`，但 `load_state` 优先读 `app/frames/`，表只是退路 | 代码路径 | "只留分帧、删掉表"这种装法起不来 | pet.pyw `main` | **已修**：两者都没有才拒绝启动 |

两处不列为缺陷，登记以免下轮重复追查：① `schedule_speech` 在静音/免打扰时按帧早退——只是几次比较，无 token 无 IO；② 交叉溶解是单侧淡出、新姿态突出部分首帧会显形，这是键控窗口的结构底线（render() 注释已写明）。

副作用一条：DA-6 修好之后，qwen娘 与 grok娘 读同一批信号文件（谁先读到谁说），一次 hook 开火只会有一只开口。

## 独立桌宠轮（9-29 下午）

需求：下载的人拿到手就该是**一只独立桌宠**（一切手动、不因 Qoder 关闭而消失）；开发机上的 qwen 单独保留"绑 Qoder 启停"。
判据：`python out/probe_audit.py` 的 J1-J11（假时钟 + 假 winutil 跑哨兵，Qoder 一律报"不存在"）。

| 编号 | 项 | 处置 |
|---|---|---|
| DB-1 | 出厂默认绑在 Qoder 上（`requires_qoder`/`follow_qoder` 都是 true），下载者手动跑起来会因为"Qoder 不在"而几分钟内自退 | `app/config.json`：两个默认改 false，新增 `"bind_qoder": false` |
| DB-2 | 哨兵只有一种语义：不看 Qoder 就没法常驻照看，看 Qoder 就没法独立当桌宠 | `app/sentinel.pyw`：加 `bind_qoder()`（启动时读一次 config+local）。false = 独立常驻：不扫进程表也不扫窗口（J2 实测 0 次）、Qoder 不在不 taskkill（J4）、`run/quit` 在哨兵启动时作废（J3，语义从"本次 Qoder 会话"变成"本次开机"）；true = 原逻辑整块保留（J5/J6/J6b） |
| DB-3 | 菜单"退出（本次 Qoder 期间不再自动回来）"在独立模式下说的是假话——那时抑制到下次开机为止 | `app/pet.pyw` `build_menu`：文案随 `bind_qoder` 出两种；菜单项个数与 4/5/6 索引未动（J10/J11） |
| DB-4 | 开发机上的绑定关系写在哪：`app/config.local.json`（gitignore 内，不进仓库）设 `requires_qoder: true` + `bind_qoder: true` | 本机行为与改动前一致（J8）。**偏差一条**：预告里说要翻 `follow_qoder`，实际保留你原来的 false——她继续站在原地不跟 Qoder 窗走；"绑 Qoder"这次只按你原话覆盖"启动/存活"这一层，跟窗是另一件事，要翻随时说 |
| DB-5 | `install-startup.ps1` 的快捷方式描述写死 "follows Qoder" | 改成 "supervisor (mode: config bind_qoder)"。`.lnk` 本身没重注册（本轮不碰开机自启），描述要等下次跑脚本才会变 |

grok娘 一行未动（本轮范围只到 qwen）。她目前的状态：`shell/config.local.json` 里 `requires_qoder: false`、哨兵没跑、开机自启没注册 → 已经是"手动起的独立桌宠"。

## 清理轮（9-29 傍晚）

需求："删掉没用的内容，让整只宠物干净"，并确认 Qoder 内置包这条线**整条撤掉**（仓库只留独立桌宠）。
判据：`tools/probe_audit.py` 41 项 + `app/selftest.py` 9 项 + `build_motion.py --check` 232 帧 + `tools/live_check.py` 真实 20 秒。
**素材零改动是这轮的硬证据**：整表重建后 `git status app/frames` 报 0 个文件变化——删掉挂饰遮罩没有改变任何一次缩框判定。

| 编号 | 项 | 处置 |
|---|---|---|
| DC-1 | Qoder 精灵表这条线：`out/spritesheet.webp` 装配、`app/assets/spritesheet.webp` 那份成品表、挂饰绘制 `draw_charm`/`charm_layer`/`CHARM*`/`MASK_BOX`、`SHEET_W/H`/`sheet_cell`、九行契约 `CONTRACT`/`base.STATES`/`COLS`/`ROWS` | **整条删除**。DA-12 那个"表只是退路"的修法随之作废——现在 `app/frames/` 是唯一素材来源，缺某个态退回 idle 并往 stderr 喊一句，`main()` 只要求 `frames/idle` 有帧 |
| DC-2 | `build_qwen_spritesheet.py` 这个名字在没表之后就是假的，且一半内容是表专用 | `git mv` → **`qwen_poses.py`**，只留素材源解析、去背、色彩拉齐、编排数据与安全区常量；删 `main/verify/preview/compose/frame_content/fit_state/CLAMPED/MIRROR/draw_charm` 与 `MOTION/FIT` 里的 `running-left` 死键（镜像态本来就整套沿用正向态） |
| DC-3 | `rigor.drop_detached`（连通分量摘挂饰）与 `pet.prepare(charm_free)` | 删。唯一调用点就是表退路。**`scale_about` 不存在**——上一轮扫描报它是死函数，实为把 `band_scale_fast` 误认，核对后未删任何东西 |
| DC-4 | 零引用：`winutil._IDLE_INFO_CLASS`、`pet.silent_until`（只被赋 0.0 又被读，半个条件永久假）、`show_bubble` 存了从不 cancel 的 `bubble_id`（generation 守卫本来就让它多余）、`selftest` 的 `import time`、`probe_q5` 的 `timedelta` | 删。`pet.self.image = photo` **保留**——那是 Tkinter 防止 PhotoImage 被回收的保命引用，不是死赋值 |
| DC-5 | `needs.Life.tick()` 算了一遍带 12h 夹取的增量、又拿**没夹取**的分钟数去 `_drain`，等于心跳路径绕过了"离线上限只在一处"那条修复（DA 轮同源问题的另一半） | 改成一次 `settle()` 拿 deltas + used，两边都用夹取后的值 |
| DC-6 | `lines/zh.json` 的 `state/running-left`、`state/running-right` 两组台词不可达：`context_line` 把态名折叠成 `split("-")[0]` | 台词留着，**让通道通**：阶梯里先按整态名试、被冷却挡住再折进 `running`。删掉手写台词不是"清理"，是丢内容 |
| DC-7 | `head_anchor()` 先把左上角 21%×27% 抹掉，那是给表里挂饰留的位子；成品帧根本不画挂饰 | 删遮罩。实测 12 个态摘掉前后锚点差 **0.0, 0.0**（气泡尖端位置不变），留着只会误导下一个读它的人 |
| DC-8 | 跟踪文件里躺着一个 234KB 的 PPM，文件名叫 `PNG`（某次探针把图重定向错了名字）；`probe/` 空目录 | `git rm PNG`、`rmdir probe` |
| DC-9 | 两个还在用的闸门（审计探针、实况检查）躺在 gitignore 的 `out/` 里，仓库看不到 | 转正进 `tools/probe_audit.py`、`tools/live_check.py`，README 的验收段直接引用 |
| DC-10 | `docs/preview.png` 是九行精灵表的截图——表没了它就成了假广告 | 由 `build_motion.contact()` 重出：**12 个态各一行 × 8 帧**，缩到 128×139 一格（1024×1656，1.2MB） |
| DC-11 | README 通篇把"跟着 Qoder 启退"当默认、`build_qwen_spritesheet` 与"两个原语"数不对、素材管线画着两条输出 | 重写：默认独立 + `bind_qoder` 可选（并写清 `requires_qoder` 与 `bind_qoder` 各管谁、为什么必须一起给）、原语三条、管线一条输出、验收四道闸门列出来。版权段沿用你远程改定的措辞，一字未动 |

**没删的三样，理由写在这**：① `shear_rows`/`band_scale`/`polar_twist`/`Spring` 这些"慢版本"运行时确实不用，但出帧管线 `build_motion` 就是它们唯一的用户，删了等于改素材质量降级；② `cfg["standalone_offset"]` 在两份配置里都没写、永远走默认值，但它是个给人留的旋钮，读法带默认不会炸；③ `ZONE_STATE` 里 `hair → failed` 这条不可达（摸头发只会出 `annoyed`），那是编排选择不是缺陷，改它等于改她的脾气，等你发话。

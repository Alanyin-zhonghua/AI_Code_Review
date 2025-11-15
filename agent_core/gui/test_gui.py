"""基于 Tkinter 的简单测试 GUI。

用于本地手动体验和调试 Agent：
- 左侧：会话列表与消息树。
- 右上：对话窗口。
- 右下：工具调用面板（read_file / list_files / ...）。
"""

import tkinter as tk
from tkinter import scrolledtext, ttk, simpledialog, messagebox, filedialog
from typing import Optional
from agent_core.api.service import run_ide_chat, stream_ide_chat
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.config.settings import settings
from agent_core.config import env_utils
from agent_core.providers.registry import PROVIDER_REGISTRY
import threading
from agent_core.flows import runner as lang_runner
from agent_core.tasks import TaskConfig, run_agent as task_run_agent


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Agent Test Console")
        self.store = JsonConversationStore()
        self.conv_id = None
        self.focus_id = None
        self.sending = False
        self.user_line_inserted = False
        self.current_stream_text = ""
        # 新增：记录当前选中的项目根目录（用于 TaskConfig.project_root）
        self.project_root: Optional[str] = getattr(settings, "workspace_root", None)
        self.env_vars = env_utils.read_env_file()
        self.conv_data = {}  # 存储显示文本到ID的映射
        self.provider_names = sorted(PROVIDER_REGISTRY.keys())
        self.model_entries = self._build_model_entries()
        self.active_provider = self.env_vars.get("DEFAULT_PROVIDER") or getattr(settings, "default_provider", self.model_entries[0][0][0] if self.model_entries else "glm")
        self.active_model = self.env_vars.get("DEFAULT_MODEL") or getattr(settings, "default_model", self.model_entries[0][0][1] if self.model_entries else "ide-chat")
        main = tk.PanedWindow(root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(main)
        right = tk.Frame(main)
        main.add(left, minsize=260)
        main.add(right)
        lf_top = tk.Frame(left)
        lf_top.pack(fill=tk.BOTH, expand=True)
        tk.Label(lf_top, text="会话").pack(anchor=tk.W)
        self.conv_list = tk.Listbox(lf_top, height=8)
        self.conv_list.pack(fill=tk.BOTH, expand=True)
        lf_btns = tk.Frame(lf_top)
        lf_btns.pack(fill=tk.X)
        tk.Button(lf_btns, text="刷新", command=self.refresh_convs).pack(side=tk.LEFT)
        tk.Button(lf_btns, text="新建", command=self.create_conv).pack(side=tk.LEFT)
        tk.Button(lf_btns, text="重命名", command=self.rename_conv).pack(side=tk.LEFT)
        tk.Button(lf_btns, text="删除", command=self.delete_conv).pack(side=tk.LEFT)
        tk.Label(left, text="消息").pack(anchor=tk.W)
        self.msg_list = tk.Listbox(left, height=14)
        self.msg_list.pack(fill=tk.BOTH, expand=True)
        self.msg_list.bind("<<ListboxSelect>>", self.on_select_msg)
        self.conv_list.bind("<<ListboxSelect>>", self.on_select_conv)
        rt_top = tk.Frame(right)
        rt_top.pack(fill=tk.BOTH, expand=True)
        self.chat = scrolledtext.ScrolledText(rt_top, width=80, height=18)
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.tag_config("user", foreground="#1a73e8")
        self.chat.tag_config("assistant", foreground="#34a853")
        self.chat.tag_config("system", foreground="#5f6368")
        self.chat.tag_config("error", foreground="#d93025")
        rt_in = tk.Frame(rt_top)
        rt_in.pack(fill=tk.X)
        self.entry = tk.Entry(rt_in)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", self.on_send_event)
        self.send_btn = tk.Button(rt_in, text="发送", command=self.on_send)
        self.send_btn.pack(side=tk.LEFT)
        # 新增：任务级 Agent 按钮，触发 TaskConfig/run_agent
        self.task_btn = tk.Button(rt_in, text="任务Agent", command=self.on_run_task)
        self.task_btn.pack(side=tk.LEFT)
        self.status = tk.Label(rt_top, text="准备就绪")
        self.status.pack(fill=tk.X)
        self.model_info = tk.Label(rt_top, text="模型: 未选择", fg="#5f6368")
        self.model_info.pack(fill=tk.X)
        workspace_frame = tk.Frame(rt_top)
        workspace_frame.pack(fill=tk.X)
        # 修改：使用“项目目录”概念，并显示当前 project_root
        tk.Label(workspace_frame, text="项目目录:").pack(side=tk.LEFT)
        self.workspace_label = tk.Label(workspace_frame, text=self.project_root or "<未选择>", fg="#5f6368")
        self.workspace_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(workspace_frame, text="选择项目目录", command=self.choose_workspace).pack(side=tk.LEFT)
        settings_panel = tk.LabelFrame(right, text="Provider / 模型")
        settings_panel.pack(fill=tk.BOTH, expand=True)
        tk.Label(settings_panel, text="可用 Provider（状态）").pack(anchor=tk.W)
        self.provider_status_list = tk.Listbox(settings_panel, height=max(3, len(self.provider_names)))
        self.provider_status_list.pack(fill=tk.X)
        self.provider_status_list.bind("<<ListboxSelect>>", self.on_provider_select)
        self.provider_env_keys = {"glm": "GLM_API_KEY", "kimi": "KIMI_API_KEY"}
        provider_key_frame = tk.Frame(settings_panel)
        provider_key_frame.pack(fill=tk.X, pady=2)
        tk.Label(provider_key_frame, text="API Key").pack(side=tk.LEFT)
        self.provider_key_entry = tk.Entry(provider_key_frame)
        self.provider_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        key_btns = tk.Frame(settings_panel)
        key_btns.pack(fill=tk.X)
        tk.Button(key_btns, text="保存 Key", command=self.save_provider_key).pack(side=tk.LEFT)
        tk.Button(key_btns, text="清除 Key", command=self.clear_provider_key).pack(side=tk.LEFT)
        tk.Label(settings_panel, text="当前模型（选择以切换）").pack(anchor=tk.W, pady=(6, 0))
        self.model_entries = self._build_model_entries()
        self.model_selector = ttk.Combobox(settings_panel, values=[entry for _, entry in self.model_entries], state="readonly")
        self.model_selector.pack(fill=tk.X)
        self.model_selector.bind("<<ComboboxSelected>>", self.on_model_entry_change)
        self.config_status = tk.Label(settings_panel, text="", fg="#5f6368")
        self.config_status.pack(fill=tk.X)

        advanced_panel = tk.LabelFrame(right, text="高级：.env 变量")
        advanced_panel.pack(fill=tk.BOTH, expand=True)
        self.env_list = tk.Listbox(advanced_panel, height=6)
        self.env_list.pack(fill=tk.BOTH, expand=True)
        self.env_list.bind("<<ListboxSelect>>", self.on_env_select)
        env_form = tk.Frame(advanced_panel)
        env_form.pack(fill=tk.X)
        self.env_key_entry = self._mk_labeled_entry(env_form, "key")
        self.env_value_entry = self._mk_labeled_entry(env_form, "value")
        env_btns = tk.Frame(advanced_panel)
        env_btns.pack(fill=tk.X)
        tk.Button(env_btns, text="添加/更新", command=self.add_env_var).pack(side=tk.LEFT)
        tk.Button(env_btns, text="删除", command=self.delete_env_var).pack(side=tk.LEFT)

        self.refresh_convs()
        self.refresh_env_view()
        self.refresh_provider_controls()
        self._update_model_display(None)

    def _mk_labeled_entry(self, parent, label):
        """创建带标签的输入框，简化表单布局。"""
        fr = tk.Frame(parent)
        fr.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(fr, text=label).pack(side=tk.LEFT)
        ent = tk.Entry(fr)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return ent

    def refresh_convs(self):
        """刷新会话列表。"""
        items = self.store.list_conversations()
        self.conv_list.delete(0, tk.END)
        self.conv_data = {}  # 存储ID到会话对象的映射
        self.active_provider = self.env_vars.get("DEFAULT_PROVIDER") or getattr(settings, "default_provider", "glm")
        self.active_model = self.env_vars.get("DEFAULT_MODEL") or getattr(settings, "default_model", "ide-chat")
        for c in items:
            display_text = c.title if c.title else f"会话 {c.id[:8]}..."
            self.conv_list.insert(tk.END, display_text)
            self.conv_data[display_text] = c.id

    def create_conv(self):
        """创建新会话并在左侧列表中选中。"""
        # 弹出对话框让用户输入标题
        title = simpledialog.askstring("新建会话", "请输入会话标题：", initialvalue="新对话")
        if title is None:  # 用户取消
            return
        
        provider, model = self._current_provider_model()
        metadata = {"title": title, "provider": provider, "model": model}
        label = "ide-helper"
        # 创建新会话
        conv = self.store.create_conversation(label, metadata)
        self.conv_id = conv.id
        self.focus_id = None
        self.chat.delete(1.0, tk.END)
        self.chat.insert(tk.END, f"[系统] 创建新会话: {title}\n", "system")
        self.status.config(text=f"会话: {title}")
        self._update_model_display(metadata)
        self.refresh_convs()
        
        # 在列表中选中新创建的会话
        for i in range(self.conv_list.size()):
            if self.conv_data.get(self.conv_list.get(i)) == conv.id:
                self.conv_list.selection_clear(0, tk.END)
                self.conv_list.selection_set(i)
                self.conv_list.see(i)
                break

    def rename_conv(self):
        """重命名当前选中的会话。"""
        sel = self.conv_list.curselection()
        if not sel:
            messagebox.showwarning("警告", "请先选择一个会话")
            return
        
        display_text = self.conv_list.get(sel[0])
        cid = self.conv_data.get(display_text)
        if not cid:
            return
        
        conv = self.store.get_conversation(cid)
        new_title = simpledialog.askstring(
            "重命名会话",
            "请输入新的标题：",
            initialvalue=conv.title
        )
        
        if new_title and new_title != conv.title:
            self.store.update_conversation_title(cid, new_title)
            self.refresh_convs()
            self.status.config(text=f"会话: {new_title}")
            messagebox.showinfo("成功", "会话标题已更新")

    def delete_conv(self):
        """删除当前选中的会话（带确认弹窗）。"""
        sel = self.conv_list.curselection()
        if not sel:
            messagebox.showwarning("警告", "请先选择一个会话")
            return
        display_text = self.conv_list.get(sel[0])
        cid = self.conv_data.get(display_text)
        if not cid:
            return
        if not messagebox.askyesno("确认删除", "删除后无法恢复，是否继续？"):
            return
        try:
            self.store.delete_conversation(cid)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        if self.conv_id == cid:
            self.conv_id = None
            self.focus_id = None
            self.chat.delete(1.0, tk.END)
            self.msg_list.delete(0, tk.END)
            self._update_model_display(None)
        self.refresh_convs()
        self.status.config(text="已删除会话")

    # ---- 环境变量 / Provider 控制 ----

    def refresh_env_view(self):
        self.env_list.delete(0, tk.END)
        for key, value in self.env_vars.items():
            self.env_list.insert(tk.END, f"{key}={value}")

    def on_env_select(self, event):
        sel = self.env_list.curselection()
        if not sel:
            return
        item = self.env_list.get(sel[0])
        if "=" not in item:
            return
        key, value = item.split("=", 1)
        self.env_key_entry.delete(0, tk.END)
        self.env_key_entry.insert(0, key.strip())
        self.env_value_entry.delete(0, tk.END)
        self.env_value_entry.insert(0, value.strip())

    def add_env_var(self):
        key = (self.env_key_entry.get() or "").strip()
        value = (self.env_value_entry.get() or "").strip()
        if not key:
            messagebox.showwarning("提示", "Key 不能为空")
            return
        self.env_vars[key] = value
        env_utils.write_env_file(self.env_vars)
        self.refresh_env_view()
        self.refresh_provider_controls()
        self._set_config_status(f"{key} 已写入 .env")

    def delete_env_var(self):
        sel = self.env_list.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先在列表中选择要删除的键")
            return
        item = self.env_list.get(sel[0])
        if "=" not in item:
            return
        key = item.split("=", 1)[0].strip()
        if key in self.env_vars:
            self.env_vars.pop(key)
            env_utils.write_env_file(self.env_vars)
            self.refresh_env_view()
            self.refresh_provider_controls()
            self._set_config_status(f"{key} 已从 .env 中删除")

    def _build_model_entries(self):
        entries = []
        for provider_name, cfg in PROVIDER_REGISTRY.items():
            for model_name in sorted(cfg.models.keys()):
                label = f"{provider_name}:{model_name}"
                entries.append(((provider_name, model_name), label))
        return entries

    def refresh_provider_controls(self):
        provider = self.active_provider or self.env_vars.get("DEFAULT_PROVIDER") or getattr(settings, "default_provider", "glm")
        self.refresh_provider_status_list()
        self.model_entries = self._build_model_entries()
        labels = [label for _, label in self.model_entries]
        self.model_selector["values"] = labels
        current_label = f"{provider}:{self.active_model}"
        if current_label in labels:
            self.model_selector.set(current_label)
        elif labels:
            self.model_selector.set(labels[0])
            provider, model = self.model_entries[0][0]
            self.active_provider = provider
            self.active_model = model
        self._select_provider_in_status(provider)

    def refresh_provider_status_list(self):
        self.provider_status_list.delete(0, tk.END)
        for name in self.provider_names:
            self.provider_status_list.insert(tk.END, self._format_provider_status(name))

    def _format_provider_status(self, name: str) -> str:
        env_key = self.provider_env_keys.get(name.lower())
        has_key = False
        if env_key:
            attr_name = env_key.lower()
            has_key = bool(self.env_vars.get(env_key) or getattr(settings, attr_name, None))
        status = "已配置" if has_key else "未配置"
        return f"{name} ({status})"

    def _select_provider_in_status(self, provider: str):
        self.provider_status_list.selection_clear(0, tk.END)
        for idx, name in enumerate(self.provider_names):
            if name == provider:
                self.provider_status_list.selection_set(idx)
                self.provider_status_list.see(idx)
                self.on_provider_select()
                break

    def on_model_entry_change(self, event=None):
        entry = self.model_selector.get().strip()
        if ":" not in entry:
            return
        provider, model = entry.split(":", 1)
        provider = provider.strip()
        model = model.strip()
        self.active_provider = provider
        self.active_model = model
        self._select_provider_in_status(provider)
        self._set_config_status(f"当前模型已切换为 {entry}")
        self._update_model_display({"provider": provider, "model": model})


    def on_provider_select(self, event=None):
        provider = self._current_selected_provider()
        if not provider:
            return
        self.active_provider = provider
        env_key = self.provider_env_keys.get(provider.lower())
        value = self.env_vars.get(env_key, "") if env_key else ""
        self.provider_key_entry.delete(0, tk.END)
        self.provider_key_entry.insert(0, value)
        matches = [label for (prov, _), label in self.model_entries if prov == provider]
        if matches:
            current = self.model_selector.get()
            if not current or not current.startswith(f"{provider}:"):
                self.model_selector.set(matches[0])
                _, model = matches[0].split(":", 1)
                self.active_model = model.strip()
                self._update_model_display({"provider": provider, "model": self.active_model})

    def save_provider_key(self):
        provider = self._current_selected_provider()
        if not provider:
            messagebox.showwarning("提示", "请先选择 Provider")
            return
        env_key = self.provider_env_keys.get(provider.lower())
        if not env_key:
            messagebox.showwarning("提示", f"Provider {provider} 暂不支持设置 Key")
            return
        value = (self.provider_key_entry.get() or "").strip()
        if not value:
            messagebox.showwarning("提示", "Key 不能为空")
            return
        self.env_vars[env_key] = value
        env_utils.write_env_file(self.env_vars)
        self.refresh_env_view()
        self.refresh_provider_controls()
        self._set_config_status(f"{env_key} 已写入 .env，请重新启动以生效")

    def clear_provider_key(self):
        provider = self._current_selected_provider()
        if not provider:
            messagebox.showwarning("提示", "请先选择 Provider")
            return
        env_key = self.provider_env_keys.get(provider.lower())
        if env_key and env_key in self.env_vars:
            self.env_vars.pop(env_key)
            env_utils.write_env_file(self.env_vars)
            self.provider_key_entry.delete(0, tk.END)
            self.refresh_env_view()
            self.refresh_provider_controls()
            self._set_config_status(f"{env_key} 已删除")

    def _current_selected_provider(self) -> Optional[str]:
        sel = self.provider_status_list.curselection()
        if sel:
            entry = self.provider_status_list.get(sel[0])
            name = entry.split("(", 1)[0].strip()
            if name:
                return name
        if self.active_provider:
            return self.active_provider
        return self.provider_names[0] if self.provider_names else None

    def _set_config_status(self, text: str):
        if hasattr(self, "config_status"):
            self.config_status.config(text=text)

    def _has_any_api_key(self) -> bool:
        return bool(
            self.env_vars.get("GLM_API_KEY")
            or self.env_vars.get("KIMI_API_KEY")
            or getattr(settings, "glm_api_key", None)
            or getattr(settings, "kimi_api_key", None)
        )

    def _update_model_display(self, meta: Optional[dict]):
        if not meta:
            provider = self.active_provider or self.env_vars.get("DEFAULT_PROVIDER") or getattr(settings, "default_provider", "-")
            model = self.active_model or self.env_vars.get("DEFAULT_MODEL") or getattr(settings, "default_model", "-")
        else:
            provider = meta.get("provider") or self.active_provider or self.env_vars.get("DEFAULT_PROVIDER") or getattr(settings, "default_provider", "-")
            model = meta.get("model") or self.active_model or self.env_vars.get("DEFAULT_MODEL") or getattr(settings, "default_model", "-")
            if provider:
                self.active_provider = provider
            if model:
                self.active_model = model
            label = f"{provider}:{model}"
            if self.model_selector["values"] and label in self.model_selector["values"]:
                self.model_selector.set(label)
        self.model_info.config(text=f"模型: {provider} ({model})")

    def _current_provider_model(self) -> tuple[str, str]:
        entry = self.model_selector.get().strip()
        if ":" in entry:
            provider, model = entry.split(":", 1)
            return provider.strip(), model.strip()
        provider = self.active_provider or self.env_vars.get("DEFAULT_PROVIDER") or getattr(settings, "default_provider", "glm")
        model = self.active_model or self.env_vars.get("DEFAULT_MODEL") or getattr(settings, "default_model", "ide-chat")
        return provider, model

    def choose_workspace(self):
        """让用户选择项目根目录，并更新运行时配置和 TaskConfig.project_root。"""
        initial = self.project_root or settings.workspace_root or "."
        path = filedialog.askdirectory(initialdir=initial, title="选择项目根目录")
        if not path:
            self._set_config_status("未选择目录")
            return
        path = path.strip()
        # 更新全局 workspace_root 与当前 GUI 的 project_root
        settings.workspace_root = path
        self.project_root = path
        self.workspace_label.config(text=path)
        self.env_vars["WORKSPACE_ROOT"] = path
        env_utils.write_env_file(self.env_vars)
        try:
            lang_runner.set_workspace_root(path)
        except Exception as exc:  # pragma: no cover - 防御
            messagebox.showerror("错误", f"更新 LangGraph 工作空间失败: {exc}")
            return
        self._set_config_status(f"已切换工作空间到 {path}")

    def _ensure_project_root(self) -> bool:
        """确保已经选择了项目根目录。"""

        root = self.project_root or settings.workspace_root
        if not root:
            messagebox.showwarning("提示", "请先选择项目根目录")
            return False
        self.project_root = root
        self.workspace_label.config(text=root)
        return True

    
    def on_select_conv(self, event):
        sel = self.conv_list.curselection()
        if not sel:
            return
        display_text = self.conv_list.get(sel[0])
        cid = self.conv_data.get(display_text)
        if not cid:
            return
        
        self.conv_id = cid
        self.focus_id = None
        conv = self.store.get_conversation(cid)
        msgs = self.store.list_messages(cid)
        self.msg_list.delete(0, tk.END)
        self.chat.delete(1.0, tk.END)
        for m in msgs:
            self.msg_list.insert(tk.END, f"{m.id}:{m.role}")
            tag = "user" if m.role == "user" else ("assistant" if m.role == "assistant" else "system")
            self.chat.insert(tk.END, f"{m.role}: {m.content}\n", tag)
        self.chat.see(tk.END)
        self.status.config(text=f"会话: {conv.title}")
        self._update_model_display(conv.meta)

    def on_select_msg(self, event):
        sel = self.msg_list.curselection()
        if not sel:
            return
        item = self.msg_list.get(sel[0])
        mid = item.split(":", 1)[0]
        self.focus_id = mid
        self.status.config(text=f"焦点消息: {mid}")

    def on_send(self):
        """发送当前输入文本，并在后台线程调用 Agent。"""
        if self.sending:
            return
        text = self.entry.get().strip()
        if not text:
            return
        if not self._ensure_project_root():
            return
        provider, model = self._current_provider_model()
        if not self._has_any_api_key():
            messagebox.showerror("缺少配置", "未检测到可用的 API Key，请先在 .env 中配置 GLM 或 KIMI 的密钥后再试。")
            return
        self.sending = True
        self.send_btn.config(state=tk.DISABLED)
        self.status.config(text="发送中...")
        self.chat.insert(tk.END, f"用户: {text}\n", "user")
        self.user_line_inserted = True
        self.current_stream_text = ""
        meta = {"provider": provider, "model": model}

        def worker():
            try:
                for event in stream_ide_chat(
                    text,
                    conversation_id=self.conv_id,
                    focus_message_id=self.focus_id,
                    meta=meta,
                    stream_granularity="char",
                    provider_name=provider,
                    model_name=model,
                ):
                    self.root.after(0, lambda ev=event: self.on_stream_event(ev))
            except NotImplementedError:
                try:
                    res = run_ide_chat(
                        text,
                        conversation_id=self.conv_id,
                        focus_message_id=self.focus_id,
                        meta=meta,
                        provider_name=provider,
                        model_name=model,
                    )
                    self.root.after(0, lambda r=res: self.on_response(r, None))
                except Exception as inner:
                    self.root.after(0, lambda err=inner: self.on_response(None, err))
            except Exception as e:
                self.root.after(0, lambda err=e: self.on_response(None, err))
        threading.Thread(target=worker, daemon=True).start()

    def on_run_task(self):
        """使用 TaskConfig/run_agent 执行一次任务级分析。"""

        if self.sending:
            return
        text = self.entry.get().strip()
        if not text:
            return
        if not self._ensure_project_root():
            return
        if not self._has_any_api_key():
            messagebox.showerror("缺少配置", "未检测到可用的 API Key，请先在 .env 中配置 GLM 或 KIMI 的密钥后再试。")
            return

        provider, model = self._current_provider_model()
        self.sending = True
        self.send_btn.config(state=tk.DISABLED)
        self.task_btn.config(state=tk.DISABLED)
        self.status.config(text="任务执行中...")
        self.chat.insert(tk.END, f"用户(任务): {text}\n", "user")
        self.chat.see(tk.END)
        project_root = self.project_root or settings.workspace_root

        def worker():
            try:
                cfg = TaskConfig(mode="read_only", max_steps=8, project_root=project_root)
                reply = task_run_agent(text, cfg, provider_name=provider, model_name=model)
                self.root.after(0, lambda r=reply: self._on_task_result(r, None))
            except Exception as exc:  # pragma: no cover - GUI 防御
                self.root.after(0, lambda err=exc: self._on_task_result("", err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_task_result(self, reply: str, err: Optional[BaseException]):
        if err:
            self.chat.insert(tk.END, f"[任务错误] {err}\n", "error")
            self.status.config(text="任务出错")
        else:
            self.chat.insert(tk.END, f"任务Agent: {reply}\n", "assistant")
            self.status.config(text="任务完成")
        self.chat.see(tk.END)
        self.sending = False
        self.send_btn.config(state=tk.NORMAL)
        if hasattr(self, "task_btn"):
            self.task_btn.config(state=tk.NORMAL)

    def on_send_event(self, event):
        self.on_send()
        return "break"

    def on_response(self, res, err):
        if err:
            self.chat.insert(tk.END, f"错误: {err}\n", "error")
            self.status.config(text="错误")
        else:
            self.conv_id = res.get("conversation_id")
            um = res.get("user_message", {}).get("content") or ""
            am = res.get("assistant_message", {}).get("content") or ""
            usage = res.get("usage") or {}
            if not self.user_line_inserted:
                self.chat.insert(tk.END, f"用户: {um}\n", "user")
            self.user_line_inserted = False
            self.chat.insert(tk.END, f"助手: {am}\n", "assistant")
            if usage:
                self.chat.insert(tk.END, f"[系统] tokens: {usage.get('total_tokens')}\n", "system")
            self.entry.delete(0, tk.END)
            self.status.config(text=f"会话: {self.conv_id}")
            try:
                conv = self.store.get_conversation(self.conv_id)
                self._update_model_display(conv.meta)
                msgs = self.store.list_messages(self.conv_id)
                self.msg_list.delete(0, tk.END)
                for m in msgs:
                    self.msg_list.insert(tk.END, f"{m.id}:{m.role}")
            except Exception:
                pass
        self.chat.see(tk.END)
        self.sending = False
        self.send_btn.config(state=tk.NORMAL)
        self.current_stream_text = ""

    def on_stream_event(self, event: dict):
        etype = event.get("type")
        if etype == "status":
            # 新增：显示模型/工具调用的状态信息
            msg = event.get("delta") or ""
            if msg:
                self.chat.insert(tk.END, msg + "\n", "system")
                self.chat.see(tk.END)
        elif etype == "delta":
            self.conv_id = event.get("conversation_id") or self.conv_id
            delta = event.get("delta") or ""
            if delta:
                if not self.current_stream_text:
                    self.chat.insert(tk.END, "助手: ", "assistant")
                self.current_stream_text += delta
                self.chat.insert(tk.END, delta, "assistant")
                self.chat.see(tk.END)
        elif etype == "final":
            self.conv_id = event.get("conversation_id") or self.conv_id
            assistant = event.get("assistant_message") or {}
            usage = event.get("usage") or {}
            if assistant and not self.current_stream_text:
                self.chat.insert(tk.END, "助手: ", "assistant")
                self.chat.insert(tk.END, assistant.get("content") or "", "assistant")
            self.chat.insert(tk.END, "\n", "assistant")
            if usage:
                self.chat.insert(tk.END, f"[系统] tokens: {usage.get('total_tokens')}\n", "system")
            self.entry.delete(0, tk.END)
            self.status.config(text=f"会话: {self.conv_id}")
            try:
                conv = self.store.get_conversation(self.conv_id)
                self._update_model_display(conv.meta)
                msgs = self.store.list_messages(self.conv_id)
                self.msg_list.delete(0, tk.END)
                for m in msgs:
                    self.msg_list.insert(tk.END, f"{m.id}:{m.role}")
            except Exception:
                pass
            self.chat.see(tk.END)
            self.sending = False
            self.send_btn.config(state=tk.NORMAL)
            self.current_stream_text = ""
            self.user_line_inserted = False
        else:
            # Unknown event type; ignore
            return

def main():
    """启动 GUI 应用。"""
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

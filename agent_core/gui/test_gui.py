import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk
from agent_core.api.service import run_ide_chat
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.tools.executor import ToolExecutor, default_tools
from agent_core.tools.definitions import ToolCall
import threading
from uuid import uuid4


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Agent Test Console")
        self.store = JsonConversationStore()
        self.tool_executor = ToolExecutor(default_tools())
        self.conv_id = None
        self.focus_id = None
        self.sending = False
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
        self.status = tk.Label(rt_top, text="准备就绪")
        self.status.pack(fill=tk.X)
        tools = tk.LabelFrame(right, text="工具")
        tools.pack(fill=tk.BOTH, expand=True)
        row1 = tk.Frame(tools)
        row1.pack(fill=tk.X)
        tk.Label(row1, text="选择").pack(side=tk.LEFT)
        self.tool_name = ttk.Combobox(row1, values=["read_file", "list_files", "search_code", "propose_edit"], state="readonly")
        self.tool_name.current(0)
        self.tool_name.pack(side=tk.LEFT)
        row2 = tk.Frame(tools)
        row2.pack(fill=tk.X)
        self.path_entry = self._mk_labeled_entry(row2, "path")
        row3 = tk.Frame(tools)
        row3.pack(fill=tk.X)
        self.dir_entry = self._mk_labeled_entry(row3, "directory")
        self.pattern_entry = self._mk_labeled_entry(row3, "pattern")
        row4 = tk.Frame(tools)
        row4.pack(fill=tk.X)
        self.query_entry = self._mk_labeled_entry(row4, "query")
        self.max_entry = self._mk_labeled_entry(row4, "max_results")
        row5 = tk.Frame(tools)
        row5.pack(fill=tk.X)
        self.range_start = self._mk_labeled_entry(row5, "start")
        self.range_end = self._mk_labeled_entry(row5, "end")
        row6 = tk.Frame(tools)
        row6.pack(fill=tk.X)
        self.new_content = self._mk_labeled_entry(row6, "new_content")
        tk.Button(tools, text="运行工具", command=self.on_run_tool).pack(anchor=tk.E)
        self.tool_out = scrolledtext.ScrolledText(tools, height=10)
        self.tool_out.pack(fill=tk.BOTH, expand=True)
        self.refresh_convs()

    def _mk_labeled_entry(self, parent, label):
        fr = tk.Frame(parent)
        fr.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(fr, text=label).pack(side=tk.LEFT)
        ent = tk.Entry(fr)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return ent

    def refresh_convs(self):
        items = self.store.list_conversations()
        self.conv_list.delete(0, tk.END)
        for c in items:
            self.conv_list.insert(tk.END, f"{c.id}")

    def create_conv(self):
        self.conv_id = None
        self.focus_id = None
        self.chat.insert(tk.END, "[系统] 新会话\n", "system")
        self.status.config(text="新会话")

    def on_select_conv(self, event):
        sel = self.conv_list.curselection()
        if not sel:
            return
        cid = self.conv_list.get(sel[0])
        self.conv_id = cid
        self.focus_id = None
        msgs = self.store.list_messages(cid)
        self.msg_list.delete(0, tk.END)
        self.chat.delete(1.0, tk.END)
        for m in msgs:
            self.msg_list.insert(tk.END, f"{m.id}:{m.role}")
            tag = "user" if m.role == "user" else ("assistant" if m.role == "assistant" else "system")
            self.chat.insert(tk.END, f"{m.role}: {m.content}\n", tag)
        self.chat.see(tk.END)
        self.status.config(text=f"会话: {cid}")

    def on_select_msg(self, event):
        sel = self.msg_list.curselection()
        if not sel:
            return
        item = self.msg_list.get(sel[0])
        mid = item.split(":", 1)[0]
        self.focus_id = mid
        self.status.config(text=f"焦点消息: {mid}")

    def on_send(self):
        if self.sending:
            return
        text = self.entry.get().strip()
        if not text:
            return
        self.sending = True
        self.send_btn.config(state=tk.DISABLED)
        self.status.config(text="发送中...")
        self.chat.insert(tk.END, "[系统] 发送中...\n", "system")
        def worker():
            try:
                res = run_ide_chat(text, conversation_id=self.conv_id, focus_message_id=self.focus_id, meta={})
                self.root.after(0, lambda: self.on_response(res, None))
            except Exception as e:
                self.root.after(0, lambda: self.on_response(None, e))
        threading.Thread(target=worker, daemon=True).start()

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
            self.chat.insert(tk.END, f"用户: {um}\n", "user")
            self.chat.insert(tk.END, f"助手: {am}\n", "assistant")
            if usage:
                self.chat.insert(tk.END, f"[系统] tokens: {usage.get('total_tokens')}\n", "system")
            self.entry.delete(0, tk.END)
            self.status.config(text=f"会话: {self.conv_id}")
            try:
                msgs = self.store.list_messages(self.conv_id)
                self.msg_list.delete(0, tk.END)
                for m in msgs:
                    self.msg_list.insert(tk.END, f"{m.id}:{m.role}")
            except Exception:
                pass
        self.chat.see(tk.END)
        self.sending = False
        self.send_btn.config(state=tk.NORMAL)

    def on_run_tool(self):
        name = self.tool_name.get().strip()
        args = {}
        p = self.path_entry.get().strip()
        d = self.dir_entry.get().strip()
        pat = self.pattern_entry.get().strip()
        q = self.query_entry.get().strip()
        mx = self.max_entry.get().strip()
        rs = self.range_start.get().strip()
        re = self.range_end.get().strip()
        nc = self.new_content.get().strip()
        if name == "read_file":
            args = {"path": p}
        elif name == "list_files":
            args = {"directory": d or ".", "pattern": pat or "*"}
        elif name == "search_code":
            args = {"directory": d or ".", "query": q, "max_results": int(mx or "50")}
        elif name == "propose_edit":
            if rs and re:
                args = {"path": p, "range": [int(rs), int(re)], "new_content": nc}
            else:
                args = {"path": p, "range": [1, 1], "new_content": nc}
        call = ToolCall(id=f"tc-{uuid4().hex}", name=name, arguments=args)
        res = self.tool_executor.execute(call)
        self.tool_out.delete(1.0, tk.END)
        self.tool_out.insert(tk.END, res.content)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
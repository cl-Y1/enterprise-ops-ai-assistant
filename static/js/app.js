/**
 * 企业智能运维知识助手 V1.3 —— 前端交互
 *
 * 说明：
 * 1. 前端只调用本项目 Flask 的 /api/chat 与 /api/feedback；
 * 2. Dify API Key 不在本文件中，也不从后端返回；
 * 3. conversation_id、message_id 按后端返回值逐条保存和使用。
 */

"use strict";

const MAX_QUERY_LENGTH = 2000;
const MAX_COMMENT_LENGTH = 300;
const FEEDBACK_TIMEOUT_MS = 30000;
const CHAT_TIMEOUT_MS = 90000;

const elements = {
  chatMessages: document.getElementById("chatMessages"),
  welcomePanel: document.getElementById("welcomePanel"),
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  sendButton: document.getElementById("sendButton"),
  newChatButton: document.getElementById("newChatButton"),
  charCount: document.getElementById("charCount"),
  serviceBadge: document.getElementById("serviceBadge"),
  serviceText: document.getElementById("serviceText"),
  feedbackDialog: document.getElementById("feedbackDialog"),
  feedbackForm: document.getElementById("feedbackForm"),
  feedbackComment: document.getElementById("feedbackComment"),
  commentCount: document.getElementById("commentCount"),
  submitFeedbackButton: document.getElementById("submitFeedbackButton"),
  closeFeedbackButton: document.getElementById("closeFeedbackButton"),
  cancelFeedbackButton: document.getElementById("cancelFeedbackButton"),
  toast: document.getElementById("toast"),
};

const state = {
  conversationId: "",
  isSending: false,
  isSubmittingFeedback: false,
  activeFeedbackMessageId: "",
  feedbackByMessage: new Map(),
  toastTimer: 0,
};

const FEEDBACK_ICONS = {
  like: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M7 10v10H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1h3Z"></path>
      <path d="M7 19h9.2a2 2 0 0 0 2-1.6l1.2-6A2 2 0 0 0 17.4 9H13l.6-3.2A2.4 2.4 0 0 0 11.2 3L7 9.5"></path>
    </svg>`,
  dislike: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M17 14V4h3a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3Z"></path>
      <path d="M17 5H7.8a2 2 0 0 0-2 1.6l-1.2 6A2 2 0 0 0 6.6 15H11l-.6 3.2A2.4 2.4 0 0 0 12.8 21L17 14.5"></path>
    </svg>`,
};

class ApiError extends Error {
  constructor(message, status = 0, code = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

/**
 * 极简、安全的 Markdown 渲染。
 * 先转义 HTML，再生成受控标签，避免 AI 回答中的 HTML/脚本被执行。
 * 不解析链接与原始 HTML。
 */
function formatInline(value) {
  return value
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
}

function renderMarkdown(text) {
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let listType = "";
  let inCodeBlock = false;
  let codeLines = [];
  let paragraphLines = [];

  const flushParagraph = () => {
    if (!paragraphLines.length) {
      return;
    }
    html.push(`<p>${paragraphLines.map(formatInline).join("<br>")}</p>`);
    paragraphLines = [];
  };

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = "";
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/g, "");

    if (line.trim().startsWith("```")) {
      flushParagraph();
      closeList();
      if (inCodeBlock) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(rawLine);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    const headingMatch = line.match(/^\s*(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      closeList();
      const level = Math.min(4, Math.max(2, headingMatch[1].length));
      html.push(`<h${level}>${formatInline(escapeHtml(headingMatch[2]))}</h${level}>`);
      continue;
    }

    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      flushParagraph();
      closeList();
      html.push("<hr>");
      continue;
    }

    const quoteMatch = line.match(/^\s*>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      closeList();
      html.push(`<blockquote>${formatInline(escapeHtml(quoteMatch[1]))}</blockquote>`);
      continue;
    }

    const bulletMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    if (bulletMatch) {
      flushParagraph();
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${formatInline(escapeHtml(bulletMatch[1]))}</li>`);
      continue;
    }

    const orderedMatch = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${formatInline(escapeHtml(orderedMatch[1]))}</li>`);
      continue;
    }

    closeList();
    paragraphLines.push(escapeHtml(line));
  }

  if (inCodeBlock && codeLines.length) {
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }
  flushParagraph();
  closeList();

  return html.join("");
}

function currentTime() {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());
}

function scrollToBottom(behavior = "smooth") {
  window.requestAnimationFrame(() => {
    elements.chatMessages.scrollTo({
      top: elements.chatMessages.scrollHeight,
      behavior,
    });
  });
}

function hideWelcome() {
  if (elements.welcomePanel && !elements.welcomePanel.hidden) {
    elements.welcomePanel.hidden = true;
  }
}

function createAvatar(role) {
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = role === "assistant" ? "AI" : "你";
  return avatar;
}

function createMessageMeta(role) {
  const meta = document.createElement("div");
  meta.className = "message-meta";

  const author = document.createElement("strong");
  author.textContent = role === "assistant" ? "知识助手" : "我";

  const time = document.createElement("span");
  time.className = "message-time";
  time.textContent = currentTime();

  meta.append(author, time);
  return meta;
}

function appendFeedbackBar(messageBody, messageId) {
  const bar = document.createElement("div");
  bar.className = "feedback-bar";
  bar.dataset.messageId = messageId;

  const buttons = [
    { rating: "like", label: "有帮助", ariaLabel: "这条回答有帮助，点赞" },
    { rating: "dislike", label: "没帮助", ariaLabel: "这条回答没有帮助，提交反馈" },
  ];

  for (const item of buttons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `feedback-btn feedback-btn--${item.rating}`;
    button.dataset.rating = item.rating;
    button.setAttribute("aria-label", item.ariaLabel);
    button.title = item.ariaLabel;
    button.innerHTML = `${FEEDBACK_ICONS[item.rating]}<span>${item.label}</span>`;
    bar.appendChild(button);
  }

  const status = document.createElement("span");
  status.className = "feedback-result";
  status.setAttribute("aria-live", "polite");
  bar.appendChild(status);

  messageBody.appendChild(bar);
}

function appendMessage({ role, text, messageId = "", isError = false }) {
  hideWelcome();

  const article = document.createElement("article");
  article.className = `message message--${role}`;

  const avatar = createAvatar(role);
  const body = document.createElement("div");
  body.className = "message-body";

  const meta = createMessageMeta(role);
  const bubble = document.createElement("div");
  bubble.className = `message-bubble${isError ? " is-error" : ""}`;

  if (role === "assistant" && !isError) {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }

  body.append(meta, bubble);

  if (role === "assistant" && messageId && !isError) {
    article.dataset.messageId = messageId;
    appendFeedbackBar(body, messageId);
  }

  article.append(avatar, body);
  elements.chatMessages.appendChild(article);
  scrollToBottom();
  return article;
}

function appendLoadingMessage() {
  hideWelcome();

  const article = document.createElement("article");
  article.className = "message message--assistant message--loading";
  article.setAttribute("aria-label", "知识助手正在生成回答");

  const avatar = createAvatar("assistant");
  const body = document.createElement("div");
  body.className = "message-body";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  const author = document.createElement("strong");
  author.textContent = "知识助手";
  meta.appendChild(author);

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.innerHTML = `
    <div class="loading-line">
      <span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>
      <span>正在检索知识库并生成回答…</span>
    </div>`;

  body.append(meta, bubble);
  article.append(avatar, body);
  elements.chatMessages.appendChild(article);
  scrollToBottom();
  return article;
}

function updateComposerState() {
  const length = elements.messageInput.value.length;
  elements.charCount.textContent = String(length);
  elements.messageInput.style.height = "auto";
  const nextHeight = Math.min(elements.messageInput.scrollHeight, 132);
  elements.messageInput.style.height = `${Math.max(nextHeight, 36)}px`;
}

function setSending(isSending) {
  state.isSending = isSending;
  elements.sendButton.disabled = isSending;
  elements.messageInput.disabled = isSending;
  elements.newChatButton.disabled = isSending;
  elements.chatForm.setAttribute("aria-busy", String(isSending));

  if (!isSending) {
    elements.messageInput.focus();
    updateComposerState();
  }
}

async function requestJson(url, { method = "POST", body = null, timeout = CHAT_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);

  try {
    const options = {
      method,
      signal: controller.signal,
      headers: { Accept: "application/json" },
    };
    if (body !== null) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok || !payload || payload.ok !== true) {
      const message =
        payload && typeof payload.message === "string" && payload.message
          ? payload.message
          : "请求未能完成，请稍后重试。";
      throw new ApiError(message, response.status, payload?.code || "");
    }

    return payload;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error.name === "AbortError") {
      throw new ApiError("请求超时，请稍后重试。", 0, "timeout");
    }
    throw new ApiError("网络连接异常，请检查网络后重试。", 0, "network_error");
  } finally {
    window.clearTimeout(timer);
  }
}

function findFeedbackBar(messageId) {
  return Array.from(elements.chatMessages.querySelectorAll(".feedback-bar")).find(
    (bar) => bar.dataset.messageId === messageId,
  );
}

function setFeedbackBarBusy(bar, isBusy) {
  if (!bar) {
    return;
  }
  bar.querySelectorAll(".feedback-btn").forEach((button) => {
    button.disabled = isBusy;
  });
}

function markFeedbackSubmitted(messageId, rating) {
  state.feedbackByMessage.set(messageId, rating);
  const bar = findFeedbackBar(messageId);
  if (!bar) {
    return;
  }

  bar.querySelectorAll(".feedback-btn").forEach((button) => {
    button.disabled = true;
    const isSelected = button.dataset.rating === rating;
    button.classList.toggle("is-active-like", isSelected && rating === "like");
    button.classList.toggle("is-active-dislike", isSelected && rating === "dislike");
  });

  const result = bar.querySelector(".feedback-result");
  if (result) {
    result.textContent = rating === "like" ? "已点赞" : "已反馈";
  }
}

async function submitLike(messageId) {
  const bar = findFeedbackBar(messageId);
  if (!bar || state.feedbackByMessage.has(messageId)) {
    return;
  }

  setFeedbackBarBusy(bar, true);
  try {
    const data = await requestJson("/api/feedback", {
      body: { message_id: messageId, rating: "like" },
      timeout: FEEDBACK_TIMEOUT_MS,
    });
    markFeedbackSubmitted(messageId, "like");
    showToast(data.message || "感谢你的认可！", "success");
  } catch (error) {
    setFeedbackBarBusy(bar, false);
    showToast(error.message, "error");
  }
}

function updateFeedbackSubmitState() {
  const selected = elements.feedbackForm.querySelector('input[name="reason"]:checked');
  elements.submitFeedbackButton.disabled = state.isSubmittingFeedback || !selected;
}

function resetFeedbackForm() {
  elements.feedbackForm.reset();
  elements.commentCount.textContent = "0";
  elements.submitFeedbackButton.classList.remove("is-loading");
  elements.submitFeedbackButton.querySelector(".button-label").textContent = "提交反馈";
  elements.closeFeedbackButton.disabled = false;
  elements.cancelFeedbackButton.disabled = false;
  elements.feedbackForm.querySelectorAll("input, textarea, button").forEach((field) => {
    field.disabled = false;
  });
  state.isSubmittingFeedback = false;
  updateFeedbackSubmitState();
}

function openFeedbackDialog(messageId) {
  if (!messageId || state.feedbackByMessage.has(messageId)) {
    return;
  }

  resetFeedbackForm();
  state.activeFeedbackMessageId = messageId;

  if (typeof elements.feedbackDialog.showModal === "function") {
    elements.feedbackDialog.showModal();
  } else {
    elements.feedbackDialog.setAttribute("open", "");
  }

  window.requestAnimationFrame(() => {
    const firstReason = elements.feedbackForm.querySelector('input[name="reason"]');
    if (firstReason) {
      firstReason.focus();
    }
  });
}

function closeFeedbackDialog() {
  if (state.isSubmittingFeedback) {
    return;
  }
  if (typeof elements.feedbackDialog.close === "function") {
    elements.feedbackDialog.close();
  } else {
    elements.feedbackDialog.removeAttribute("open");
  }
}

function setFeedbackSubmitting(isSubmitting) {
  state.isSubmittingFeedback = isSubmitting;
  elements.closeFeedbackButton.disabled = isSubmitting;
  elements.cancelFeedbackButton.disabled = isSubmitting;
  elements.feedbackForm.querySelectorAll('input[name="reason"], textarea').forEach((field) => {
    field.disabled = isSubmitting;
  });
  elements.submitFeedbackButton.classList.toggle("is-loading", isSubmitting);
  elements.submitFeedbackButton.querySelector(".button-label").textContent = isSubmitting
    ? "提交中…"
    : "提交反馈";
  updateFeedbackSubmitState();
}

async function handleFeedbackSubmit(event) {
  event.preventDefault();
  if (state.isSubmittingFeedback) {
    return;
  }

  const messageId = state.activeFeedbackMessageId;
  const selected = elements.feedbackForm.querySelector('input[name="reason"]:checked');
  if (!messageId || !selected) {
    showToast("请选择反馈原因后再提交。", "error");
    return;
  }

  const reason = selected.value;
  const comment = elements.feedbackComment.value.trim();
  if (comment.length > MAX_COMMENT_LENGTH) {
    showToast(`补充说明不能超过 ${MAX_COMMENT_LENGTH} 个字符。`, "error");
    return;
  }

  setFeedbackSubmitting(true);
  try {
    const data = await requestJson("/api/feedback", {
      body: {
        message_id: messageId,
        rating: "dislike",
        reason,
        comment,
      },
      timeout: FEEDBACK_TIMEOUT_MS,
    });
    markFeedbackSubmitted(messageId, "dislike");
    elements.feedbackDialog.close();
    showToast(data.message || "感谢反馈，我们将持续优化知识助手。", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setFeedbackSubmitting(false);
  }
}

function showToast(message, type = "success") {
  window.clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast is-visible is-${type}`;
  state.toastTimer = window.setTimeout(
    () => {
      elements.toast.className = "toast";
    },
    type === "error" ? 5200 : 3600,
  );
}

function setServiceBadge(mode, text, title) {
  elements.serviceBadge.className = `service-badge ${mode}`;
  elements.serviceText.textContent = text;
  elements.serviceBadge.title = title;
}

async function checkServiceStatus() {
  try {
    const data = await requestJson("/api/health", { method: "GET", timeout: 15000 });
    if (data.configured) {
      setServiceBadge("", "服务已配置", "后端已读取 Dify API Key，未校验 Key 是否有效");
    } else {
      setServiceBadge(
        "is-warning",
        "待配置 API Key",
        "请在后端 .env 文件中配置 DIFY_API_KEY 后重启服务",
      );
    }
  } catch {
    setServiceBadge("is-warning", "服务状态未知", "无法连接本地 Flask 服务");
  }
}

async function handleChatSubmit(event) {
  event.preventDefault();
  if (state.isSending) {
    return;
  }

  const query = elements.messageInput.value.trim();
  if (!query) {
    showToast("请输入问题后再发送。", "error");
    elements.messageInput.focus();
    return;
  }
  if (query.length > MAX_QUERY_LENGTH) {
    showToast(`问题不能超过 ${MAX_QUERY_LENGTH} 个字符。`, "error");
    return;
  }

  appendMessage({ role: "user", text: query });
  elements.messageInput.value = "";
  updateComposerState();
  setSending(true);
  const loadingMessage = appendLoadingMessage();

  try {
    const data = await requestJson("/api/chat", {
      body: {
        query,
        conversation_id: state.conversationId,
      },
    });

    state.conversationId = data.conversation_id;
    loadingMessage.remove();
    appendMessage({
      role: "assistant",
      text: data.answer,
      messageId: data.message_id,
    });
  } catch (error) {
    loadingMessage.remove();

    if (error.code === "conversation_not_found") {
      state.conversationId = "";
    }

    const errorText = `抱歉，未能获取回答。${error.message}`;
    appendMessage({ role: "assistant", text: errorText, isError: true });
    showToast(error.message, "error");

    // 保留用户刚输入的问题，方便直接重试，不丢失内容。
    if (!elements.messageInput.value) {
      elements.messageInput.value = query;
      updateComposerState();
    }
  } finally {
    setSending(false);
  }
}

function startNewChat() {
  if (state.isSending) {
    showToast("请等待当前回答完成后再开始新对话。", "error");
    return;
  }

  const hasMessages = Boolean(elements.chatMessages.querySelector(".message"));
  if (hasMessages && !window.confirm("确定开始新对话吗？当前页面中的对话将被清空。")) {
    return;
  }

  state.conversationId = "";
  state.feedbackByMessage.clear();
  state.activeFeedbackMessageId = "";
  elements.chatMessages.querySelectorAll(".message").forEach((message) => message.remove());
  elements.welcomePanel.hidden = false;
  elements.messageInput.value = "";
  updateComposerState();
  elements.chatMessages.scrollTo({ top: 0, behavior: "smooth" });
  elements.messageInput.focus();

  if (hasMessages) {
    showToast("已开始新对话，可以继续提问。", "success");
  }
}

function handleFeedbackButtonClick(event) {
  const button = event.target.closest(".feedback-btn");
  if (!button) {
    return;
  }

  const bar = button.closest(".feedback-bar");
  const messageId = bar?.dataset.messageId || "";
  if (!messageId || state.feedbackByMessage.has(messageId)) {
    return;
  }

  if (button.dataset.rating === "like") {
    submitLike(messageId);
  } else {
    openFeedbackDialog(messageId);
  }
}

function bindEvents() {
  elements.chatForm.addEventListener("submit", handleChatSubmit);

  elements.messageInput.addEventListener("input", updateComposerState);
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      elements.chatForm.requestSubmit();
    }
  });

  elements.newChatButton.addEventListener("click", startNewChat);
  elements.chatMessages.addEventListener("click", handleFeedbackButtonClick);

  document.querySelectorAll(".suggestion-card").forEach((card) => {
    card.addEventListener("click", () => {
      const question = card.dataset.question || "";
      if (!question || state.isSending) {
        return;
      }
      elements.messageInput.value = question;
      updateComposerState();
      elements.messageInput.focus();
      elements.messageInput.setSelectionRange(question.length, question.length);
    });
  });

  elements.feedbackForm.addEventListener("submit", handleFeedbackSubmit);
  elements.feedbackForm.addEventListener("change", (event) => {
    if (event.target.name === "reason") {
      updateFeedbackSubmitState();
    }
  });
  elements.feedbackComment.addEventListener("input", () => {
    elements.commentCount.textContent = String(elements.feedbackComment.value.length);
  });

  elements.closeFeedbackButton.addEventListener("click", closeFeedbackDialog);
  elements.cancelFeedbackButton.addEventListener("click", closeFeedbackDialog);

  elements.feedbackDialog.addEventListener("click", (event) => {
    if (event.target === elements.feedbackDialog) {
      closeFeedbackDialog();
    }
  });

  elements.feedbackDialog.addEventListener("cancel", (event) => {
    if (state.isSubmittingFeedback) {
      event.preventDefault();
    }
  });

  elements.feedbackDialog.addEventListener("close", () => {
    state.activeFeedbackMessageId = "";
    resetFeedbackForm();
  });
}

function init() {
  bindEvents();
  updateComposerState();
  checkServiceStatus();
  elements.messageInput.focus();
}

init();

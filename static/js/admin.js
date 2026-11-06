/** 文档版本管理后台的轻量交互。 */
"use strict";

document.addEventListener("click", async (event) => {
  const copyButton = event.target.closest("[data-copy-target]");
  if (copyButton) {
    const target = document.getElementById(copyButton.dataset.copyTarget);
    if (!target) {
      return;
    }
    const text = target.textContent || "";
    const original = copyButton.textContent;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "");
        helper.className = "clipboard-helper";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      copyButton.textContent = "已复制";
    } catch {
      copyButton.textContent = "复制失败";
    }
    window.setTimeout(() => {
      copyButton.textContent = original;
    }, 1600);
  }
});

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

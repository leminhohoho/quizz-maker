// quizz UI: math rendering, composer serialization, step editing, keyboard shortcuts.
(() => {
  "use strict";

  const KATEX_OPTIONS = {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\(", right: "\\)", display: false },
      { left: "$", right: "$", display: false },
    ],
    throwOnError: false,
  };

  function renderMath(root) {
    if (window.renderMathInElement) window.renderMathInElement(root, KATEX_OPTIONS);
  }

  function configureMathLive() {
    const MFE = window.MathfieldElement;
    if (!MFE) return;
    MFE.soundsDirectory = null;
    MFE.keypressSound = null;
    MFE.plonkSound = null;
  }

  // ---------------------------------------------------------------- composer -> JSON
  function serialize(form) {
    const type = form.dataset.type;
    if (type === "mcq") {
      const picked = form.querySelector('input[name="choice"]:checked');
      return picked ? { choice: picked.value } : null;
    }
    if (type === "multi_select") {
      const picked = [...form.querySelectorAll('input[name="choices"]:checked')].map((i) => i.value);
      return picked.length ? { choices: picked } : null;
    }
    if (type === "fill_blank") {
      const blanks = {};
      let any = false;
      document.querySelectorAll("input.blank[data-blank]").forEach((input) => {
        blanks[input.dataset.blank] = input.value;
        if (input.value.trim()) any = true;
      });
      return any ? { blanks } : null;
    }
    if (type === "math_answer") {
      const field = form.querySelector('math-field[data-name="answer"]') || form.querySelector('input[name="answer"]');
      const value = (field.value || "").trim();
      return value ? { answer: value } : null;
    }
    if (type === "exercise") {
      const steps = [...form.querySelectorAll(".step")]
        .map((step) => ({
          latex: (step.querySelector("math-field").value || "").trim(),
          justification: (step.querySelector(".why").value || "").trim(),
        }))
        .filter((s) => s.latex);
      return steps.length ? { steps } : null;
    }
    return null;
  }

  function nudge(form, message) {
    const slot = form.querySelector("#composer-error");
    if (slot) slot.innerHTML = `<div class="error-box" role="alert">${message}</div>`;
    form.classList.remove("shake");
    void form.offsetWidth;
    form.classList.add("shake");
  }

  document.addEventListener("htmx:configRequest", (evt) => {
    const form = evt.detail.elt;
    if (!(form instanceof HTMLFormElement) || form.id !== "composer") return;
    const response = serialize(form);
    if (!response) {
      evt.preventDefault();
      nudge(form, "Answer first.");
      return;
    }
    evt.detail.parameters = { response: JSON.stringify(response) };
  });

  // 400 responses carry an inline error fragment: show it inside the composer instead of replacing it.
  document.addEventListener("htmx:beforeSwap", (evt) => {
    if (evt.detail.xhr.status === 400) {
      const slot = document.querySelector("#composer-error");
      if (slot) {
        evt.detail.shouldSwap = true;
        evt.detail.isError = false;
        evt.detail.target = slot;
      }
    }
  });

  document.addEventListener("htmx:afterSwap", (evt) => {
    renderMath(evt.detail.target);
    const next = document.querySelector("[data-next]");
    if (next && evt.detail.target.id === "answer-area") next.focus({ preventScroll: true });
  });

  // ---------------------------------------------------------------- exercise steps
  function renumber(form) {
    form.querySelectorAll(".step .n").forEach((n, i) => (n.textContent = String(i + 1)));
  }

  function addStep(after) {
    const form = after.closest("form");
    const step = after.cloneNode(true);
    const field = step.querySelector("math-field");
    const fresh = document.createElement("math-field");
    fresh.className = field.className;
    field.replaceWith(fresh);
    const why = step.querySelector(".why");
    why.value = "";
    why.hidden = true;
    after.after(step);
    renumber(form);
    requestAnimationFrame(() => fresh.focus()); // MathLive mounts its editor one frame after insertion
    return step;
  }

  function removeStep(step) {
    const form = step.closest("form");
    if (form.querySelectorAll(".step").length <= 1) return;
    const prev = step.previousElementSibling || step.nextElementSibling;
    step.remove();
    renumber(form);
    prev?.querySelector("math-field")?.focus();
  }

  function toggleReason(step) {
    const why = step.querySelector(".why");
    why.hidden = !why.hidden;
    if (!why.hidden) why.focus();
  }

  document.addEventListener("click", (evt) => {
    const add = evt.target.closest(".add-step");
    if (add) {
      const steps = add.closest("form").querySelectorAll(".step");
      addStep(steps[steps.length - 1]);
      return;
    }
    const rm = evt.target.closest(".step .rm");
    if (rm) removeStep(rm.closest(".step"));
    const toggle = evt.target.closest("[data-toggle-sidebar]");
    if (toggle) {
      const shell = document.getElementById("shell");
      shell.classList.toggle("collapsed");
      localStorage.setItem("quizz.sidebar", shell.classList.contains("collapsed") ? "collapsed" : "open");
    }
  });

  // ---------------------------------------------------------------- keyboard
  function typingTarget(el) {
    return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "MATH-FIELD");
  }

  document.addEventListener(
    "keydown",
    (evt) => {
      const form = document.getElementById("composer");
      const active = document.activeElement;
      if (evt.key === "Enter" && (evt.metaKey || evt.ctrlKey) && form) {
        evt.preventDefault();
        evt.stopPropagation();
        form.requestSubmit();
        return;
      }
      const step = active && active.closest && active.closest(".step");
      if (step && evt.key === "Enter" && !evt.shiftKey) {
        evt.preventDefault();
        evt.stopPropagation();
        if (evt.altKey) toggleReason(step);
        else if (active.tagName === "MATH-FIELD") addStep(step);
        else step.querySelector("math-field").focus();
        return;
      }
      if (step && evt.key === "Backspace" && active.tagName === "MATH-FIELD" && !active.value) {
        if (form.querySelectorAll(".step").length > 1) {
          evt.preventDefault();
          evt.stopPropagation();
          removeStep(step);
        }
        return;
      }
      if (typingTarget(active)) {
        if (evt.key === "Enter" && active.tagName === "INPUT" && form && !active.classList.contains("why")) {
          evt.preventDefault();
          form.requestSubmit();
        }
        return;
      }
      if (form && /^[1-9]$/.test(evt.key)) {
        const inputs = form.querySelectorAll(".opt input");
        const input = inputs[Number(evt.key) - 1];
        if (input) {
          input.click();
          evt.preventDefault();
        }
        return;
      }
      const next = document.querySelector("[data-next]");
      if (evt.key === "Enter" && next && !form) {
        evt.preventDefault();
        next.click();
      }
    },
    true,
  );

  // ---------------------------------------------------------------- boot
  document.addEventListener("DOMContentLoaded", () => {
    if (localStorage.getItem("quizz.sidebar") === "collapsed") document.getElementById("shell")?.classList.add("collapsed");
    configureMathLive();
    renderMath(document.body);
    const first = document.querySelector("#composer math-field, #composer input.text-answer, input.blank");
    if (first) first.focus();
  });
})();

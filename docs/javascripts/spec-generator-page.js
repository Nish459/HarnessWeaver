/*
 * The spec generator page (docs/learn/spec-generator.md): wires its forms to the writers
 * in spec-generator.js, and shows the document the chosen form writes as the reader makes
 * their choices, with the files it refers to and the commands that install, check and use
 * it.
 */

(function () {
  "use strict";

  /* What each kind of file holds, for the page's list. */
  var KINDS = {
    prompt: function () { return "the task's prompt"; },
    model: function (name) { return "the Pydantic model " + name; },
    function: function (name) { return "the function " + name; },
    agent: function (name) { return "the Pydantic AI agent " + name; },
    manifest: function (name) { return "the manifest of the tool " + name; },
    documents: function () { return "the documents to retrieve from"; },
    dataset: function (name) { return "the eval cases of the task " + name + ", which eval run reads"; },
    plugin: function (name) { return "your plugin, namespace " + name; },
    middleware: function (name) { return "the middleware " + name; },
  };

  /* The form a file of the list can be written with, and the values to start it from. */
  var WRITE_WITH = {
    manifest: function (file) { return ["tool", { name: file.name, handler: "", description: "" }]; },
    dataset: function (file) {
      return ["eval", { suite: file.path.replace(/^.*\/|\.yaml$/g, ""), task: file.name }];
    },
  };

  /*
   * Whether a part of a form shows: data-when="field=a|b" for those values of the field,
   * with "&" between conditions that must all hold and "||" between alternatives.
   */
  function shows(form, rule) {
    function valueOf(field) {
      var element = form.elements[field];
      if (!element) return "";
      return element.type === "checkbox" ? (element.checked ? "on" : "") : element.value;
    }
    return rule.split("||").some(function (alternative) {
      return alternative.split("&").every(function (condition) {
        var parts = condition.trim().split("=");
        return parts[1].split("|").indexOf(valueOf(parts[0])) >= 0;
      });
    });
  }

  /* Wire the forms to the output beside them, if this page has the generator. */
  function setUp() {
    var root = document.getElementById("hw-gen");
    var generator = globalThis.hwSpecGenerator;
    if (!root || !generator) return;
    var forms = {};
    root.querySelectorAll("form[data-doc]").forEach(function (form) {
      forms[form.getAttribute("data-doc")] = form;
    });
    var picker = root.querySelectorAll('input[name="hw-gen-doc"]');
    var output = document.getElementById("hw-gen-yaml");
    var fileName = document.getElementById("hw-gen-file");
    var fileList = document.getElementById("hw-gen-files");
    var blocks = ["install", "check", "use"].map(function (name) {
      return document.getElementById("hw-gen-" + name);
    });
    // Each form's model provider, so a new one's model defaults can replace the last one's.
    var providers = {};
    Object.keys(forms).forEach(function (doc) {
      var select = forms[doc].elements.provider;
      if (select) providers[doc] = select.value;
    });
    var current;

    function chosen() {
      var checked = root.querySelector('input[name="hw-gen-doc"]:checked');
      return checked ? checked.value : "harness";
    }

    function render() {
      var doc = chosen();
      var form = forms[doc];
      Object.keys(forms).forEach(function (other) { forms[other].hidden = other !== doc; });
      // A new provider's model defaults replace the last one's, unless the reader typed
      // others, in a form that starts with them filled in. The others leave an empty alias
      // to the app spec or the provider.
      var select = form.elements.provider;
      var filled = form.elements.fast_model && form.elements.fast_model.defaultValue !== "";
      if (select && select.value !== providers[doc] && filled) {
        ["fast", "strong"].forEach(function (alias) {
          var input = form.elements[alias + "_model"];
          var before = generator.MODELS[providers[doc]];
          var after = generator.MODELS[select.value];
          if (input && before && after && input.value === before[alias]) input.value = after[alias];
        });
      }
      if (select) providers[doc] = select.value;
      form.querySelectorAll("[data-when]").forEach(function (part) {
        part.hidden = !shows(form, part.getAttribute("data-when"));
      });

      current = generator.buildSpec(Object.fromEntries(new FormData(form)));
      fileName.textContent = current.file;
      output.textContent = current.yaml;
      blocks.forEach(function (block, i) {
        var text = [current.install, current.check, [current.use]][i].join("\n");
        block.textContent = text;
        block.closest("[data-block]").hidden = text === "";
      });
      renderFiles(current.files);
    }

    /* The files the document refers to, by path, each with what goes in it. */
    function renderFiles(files) {
      var byPath = {};
      files.forEach(function (file) {
        (byPath[file.path] = byPath[file.path] || []).push(file);
      });
      fileList.replaceChildren.apply(fileList, Object.keys(byPath).map(function (path) {
        var item = document.createElement("li");
        var code = document.createElement("code");
        code.textContent = path;
        item.append(code, ": " + byPath[path].map(function (file) {
          return KINDS[file.kind](file.name);
        }).join(", "));
        byPath[path].forEach(function (file) {
          if (!WRITE_WITH[file.kind]) return;
          var button = document.createElement("button");
          button.type = "button";
          button.className = "hw-gen__link";
          button.textContent = "Write it here";
          button.addEventListener("click", function () { open.apply(null, WRITE_WITH[file.kind](file)); });
          item.append(" ", button);
        });
        return item;
      }));
      fileList.parentElement.hidden = files.length === 0;
    }

    /* Switch to a document's form, with some of its fields set. */
    function open(doc, values) {
      picker.forEach(function (radio) { radio.checked = radio.value === doc; });
      Object.keys(values).forEach(function (field) { forms[doc].elements[field].value = values[field]; });
      render();
      root.scrollIntoView({ behavior: "smooth" });
    }

    picker.forEach(function (radio) { radio.addEventListener("change", render); });
    Object.keys(forms).forEach(function (doc) {
      forms[doc].addEventListener("input", render);
      forms[doc].addEventListener("change", render);
      // The reset event comes before the form's values are reset.
      forms[doc].addEventListener("reset", function () { setTimeout(render); });
    });

    document.getElementById("hw-gen-copy").addEventListener("click", function (event) {
      var button = event.currentTarget;
      navigator.clipboard.writeText(current.yaml).then(function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy"; }, 1500);
      });
    });
    document.getElementById("hw-gen-download").addEventListener("click", function () {
      var link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([current.yaml], { type: "application/yaml" }));
      link.download = current.file.split("/").pop();
      link.click();
      URL.revokeObjectURL(link.href);
    });
    render();
  }

  if (typeof document$ !== "undefined") {
    // Material's document$ fires on every page load, including instant navigation.
    document$.subscribe(setUp);
  } else {
    document.addEventListener("DOMContentLoaded", setUp);
  }
})();

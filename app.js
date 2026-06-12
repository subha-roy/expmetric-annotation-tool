(function () {
  var DATASET = "pilot_100";
  var DATA_URL = "data/pilot_decomposed.json";
  var IMAGE_DIR = "images";
  var STORAGE_PREFIX = "expmetric_annotations_";
  var LAST_ANNOTATOR_KEY = "expmetric_last_annotator_" + DATASET;

  var OVERALL_OPTIONS = [
    { value: 1, label: "1 - Completely incorrect" },
    { value: 2, label: "2 - Mostly incorrect" },
    { value: 3, label: "3 - Partially correct" },
    { value: 4, label: "4 - Mostly correct" },
    { value: 5, label: "5 - Fully correct" }
  ];

  var OPTIONS = {
    decomp_quality: [
      { value: "reasonable", label: "Reasonable" },
      { value: "needs_split", label: "Needs split" },
      { value: "needs_merge", label: "Needs merge" },
      { value: "missing", label: "Missing" }
    ],
    correctness: [
      { value: "fully_correct", label: "Fully correct" },
      { value: "partially_correct", label: "Partially correct" },
      { value: "incorrect", label: "Incorrect" },
      { value: "cannot_judge", label: "Cannot judge" }
    ],
    severity: [
      { value: "critical", label: "Critical" },
      { value: "medium", label: "Medium" },
      { value: "minor", label: "Minor" }
    ],
    error_type: [
      { value: "hallucinated_object", label: "Hallucinated object" },
      { value: "wrong_attribute", label: "Wrong attribute" },
      { value: "wrong_relation", label: "Wrong relation" },
      { value: "wrong_count", label: "Wrong count" },
      { value: "missing_object", label: "Missing object" },
      { value: "other", label: "Other" }
    ]
  };

  var samples = [];
  var annotatorId = "";
  var state = {
    dataset: DATASET,
    currentIndex: 0,
    annotations: {}
  };
  var dom = {};

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function safeId(value) {
    return String(value == null ? "" : value).replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function emptyState() {
    return {
      dataset: DATASET,
      currentIndex: 0,
      annotations: {}
    };
  }

  function storageKey(id) {
    return STORAGE_PREFIX + DATASET + "_" + id;
  }

  function legacyStorageKey(id) {
    return STORAGE_PREFIX + id;
  }

  function isValid(field, value) {
    var options = OPTIONS[field] || [];
    for (var i = 0; i < options.length; i += 1) {
      if (options[i].value === value) {
        return true;
      }
    }
    return false;
  }

  function showStatus(message, type) {
    if (!message) {
      dom.statusPanel.className = "status-panel";
      dom.statusPanel.textContent = "";
      return;
    }
    dom.statusPanel.className = "status-panel visible " + (type || "");
    dom.statusPanel.textContent = message;
  }

  function setNavDisabled(disabled) {
    dom.prevBtn.disabled = disabled;
    dom.saveBtn.disabled = disabled;
    dom.nextBtn.disabled = disabled;
    dom.resetCurrentBtn.disabled = disabled;
  }

  function clampIndex() {
    if (!samples.length) {
      state.currentIndex = 0;
      return;
    }
    if (!Number.isInteger(state.currentIndex)) {
      state.currentIndex = 0;
    }
    state.currentIndex = Math.max(0, Math.min(state.currentIndex, samples.length - 1));
  }

  function saveState() {
    if (!annotatorId) {
      return;
    }
    clampIndex();
    localStorage.setItem(LAST_ANNOTATOR_KEY, annotatorId);
    localStorage.setItem(storageKey(annotatorId), JSON.stringify(state));
  }

  function loadStateForAnnotator(id) {
    if (!id) {
      state = emptyState();
      return;
    }

    var raw = localStorage.getItem(storageKey(id)) || localStorage.getItem(legacyStorageKey(id));
    if (!raw) {
      state = emptyState();
      return;
    }

    try {
      var parsed = JSON.parse(raw);
      state = {
        dataset: DATASET,
        currentIndex: Number.isInteger(parsed.currentIndex) ? parsed.currentIndex : 0,
        annotations: parsed.annotations && typeof parsed.annotations === "object" ? parsed.annotations : {}
      };
    } catch (error) {
      state = emptyState();
    }
    clampIndex();
    if (migrateStoredValues()) {
      saveState();
    }
  }

  function normalizeCorrectness(value) {
    var map = {
      correct: "fully_correct",
      partial: "partially_correct",
      wrong: "incorrect",
      unclear: "cannot_judge"
    };
    return map[value] || value || null;
  }

  function migrateStoredValues() {
    var changed = false;
    var annotations = state.annotations || {};
    var sampleIds = Object.keys(annotations);

    for (var i = 0; i < sampleIds.length; i += 1) {
      var annotation = annotations[sampleIds[i]];
      var parts = annotation && Array.isArray(annotation.parts) ? annotation.parts : [];
      for (var j = 0; j < parts.length; j += 1) {
        var part = parts[j];
        var correctness = normalizeCorrectness(part.correctness || part.label);
        var severity = part.severity || part.importance || null;

        if (part.correctness !== correctness) {
          part.correctness = correctness;
          changed = true;
        }
        if (part.severity !== severity) {
          part.severity = severity;
          changed = true;
        }
        if (Object.prototype.hasOwnProperty.call(part, "importance")) {
          delete part.importance;
          changed = true;
        }
        if (part.correctness !== "incorrect" && part.error_type !== null) {
          part.error_type = null;
          changed = true;
        }
      }
    }

    return changed;
  }

  function createAnnotation(sample) {
    var parts = [];
    for (var i = 0; i < (sample.parts || []).length; i += 1) {
      var part = sample.parts[i];
      parts.push({
        part_id: part.part_id,
        text: part.text,
        type: part.type,
        decomp_quality: null,
        correctness: null,
        severity: null,
        error_type: null
      });
    }

    return {
      sample_id: sample.sample_id,
      image_id: sample.image_id,
      image_file: sample.image_file,
      caption: sample.caption,
      overall_score: null,
      parts: parts
    };
  }

  function normalizeAnnotation(annotation) {
    for (var i = 0; i < (annotation.parts || []).length; i += 1) {
      var part = annotation.parts[i];
      part.correctness = normalizeCorrectness(part.correctness || part.label);
      if (part.correctness !== "incorrect") {
        part.error_type = null;
      }
    }
  }

  function ensureAnnotation(sample) {
    if (!state.annotations[sample.sample_id]) {
      state.annotations[sample.sample_id] = createAnnotation(sample);
    }

    var annotation = state.annotations[sample.sample_id];
    annotation.sample_id = sample.sample_id;
    annotation.image_id = sample.image_id;
    annotation.image_file = sample.image_file;
    annotation.caption = sample.caption;
    if ([1, 2, 3, 4, 5].indexOf(annotation.overall_score) === -1) {
      annotation.overall_score = null;
    }

    var existingById = {};
    for (var i = 0; i < (annotation.parts || []).length; i += 1) {
      existingById[annotation.parts[i].part_id] = annotation.parts[i];
    }

    var nextParts = [];
    for (var j = 0; j < (sample.parts || []).length; j += 1) {
      var source = sample.parts[j];
      var existing = existingById[source.part_id] || {};
      var correctness = normalizeCorrectness(existing.correctness || existing.label);
      var severity = existing.severity || existing.importance || null;

      nextParts.push({
        part_id: source.part_id,
        text: source.text,
        type: source.type,
        decomp_quality: isValid("decomp_quality", existing.decomp_quality) ? existing.decomp_quality : null,
        correctness: isValid("correctness", correctness) ? correctness : null,
        severity: isValid("severity", severity) ? severity : null,
        error_type: correctness === "incorrect" && isValid("error_type", existing.error_type) ? existing.error_type : null
      });
    }

    annotation.parts = nextParts;
    normalizeAnnotation(annotation);
    return annotation;
  }

  function currentSample() {
    return samples[state.currentIndex] || null;
  }

  function currentAnnotation() {
    var sample = currentSample();
    return sample ? ensureAnnotation(sample) : null;
  }

  function validate(annotation, requireAnnotator) {
    normalizeAnnotation(annotation);
    var errors = [];

    if (requireAnnotator && !annotatorId) {
      errors.push("Annotator ID is required.");
    }
    if ([1, 2, 3, 4, 5].indexOf(annotation.overall_score) === -1) {
      errors.push("Overall correctness score is required.");
    }

    for (var i = 0; i < annotation.parts.length; i += 1) {
      var part = annotation.parts[i];
      var name = part.part_id + " (" + part.text + ")";
      if (!isValid("decomp_quality", part.decomp_quality)) {
        errors.push(name + ": decomposition quality is required.");
      }
      if (!isValid("correctness", part.correctness)) {
        errors.push(name + ": correctness is required.");
      }
      if (!isValid("severity", part.severity)) {
        errors.push(name + ": importance is required.");
      }
      if (part.correctness === "incorrect" && !isValid("error_type", part.error_type)) {
        errors.push(name + ": error type is required when correctness is incorrect.");
      }
    }

    return errors;
  }

  function exportRow(annotation) {
    normalizeAnnotation(annotation);
    var parts = [];
    for (var i = 0; i < annotation.parts.length; i += 1) {
      var part = annotation.parts[i];
      parts.push({
        part_id: part.part_id,
        text: part.text,
        type: part.type,
        decomp_quality: part.decomp_quality,
        correctness: part.correctness,
        severity: part.severity,
        error_type: part.correctness === "incorrect" ? part.error_type : null
      });
    }

    return {
      sample_id: annotation.sample_id,
      image_id: annotation.image_id,
      image_file: annotation.image_file,
      caption: annotation.caption,
      overall_score: annotation.overall_score,
      parts: parts
    };
  }

  function completedAnnotations() {
    var output = [];
    for (var i = 0; i < samples.length; i += 1) {
      var annotation = state.annotations[samples[i].sample_id];
      if (annotation && validate(annotation, false).length === 0) {
        output.push(exportRow(annotation));
      }
    }
    return output;
  }

  function renderRadioGroup(part, field) {
    var options = OPTIONS[field];
    var html = "";
    for (var i = 0; i < options.length; i += 1) {
      var option = options[i];
      var checked = part[field] === option.value ? "checked" : "";
      var selected = part[field] === option.value ? " selected" : "";
      html += '<label class="radio-pill' + selected + '">' +
        '<input type="radio" name="' + safeId(part.part_id) + "_" + field + '" data-part-id="' + escapeHtml(part.part_id) + '" data-field="' + field + '" value="' + option.value + '" ' + checked + ">" +
        "<span>" + escapeHtml(option.label) + "</span>" +
        "</label>";
    }
    return html;
  }

  function renderOverallOptions(annotation) {
    var html = "";
    for (var i = 0; i < OVERALL_OPTIONS.length; i += 1) {
      var option = OVERALL_OPTIONS[i];
      var checked = annotation.overall_score === option.value ? "checked" : "";
      var selected = annotation.overall_score === option.value ? " selected" : "";
      html += '<label class="radio-pill' + selected + '">' +
        '<input type="radio" name="overall_score" value="' + option.value + '" ' + checked + ">" +
        "<span>" + escapeHtml(option.label) + "</span>" +
        "</label>";
    }
    return html;
  }

  function renderErrorOptions(selectedValue) {
    var html = "";
    for (var i = 0; i < OPTIONS.error_type.length; i += 1) {
      var option = OPTIONS.error_type[i];
      var selected = selectedValue === option.value ? "selected" : "";
      html += '<option value="' + option.value + '" ' + selected + ">" + escapeHtml(option.label) + "</option>";
    }
    return html;
  }

  function renderPartCard(part) {
    var errorMarkup = "";
    if (part.correctness === "incorrect") {
      errorMarkup = '<div class="field-group">' +
        '<div class="field-title">Error Type</div>' +
        '<div class="select-row">' +
        '<select data-part-id="' + escapeHtml(part.part_id) + '" data-field="error_type">' +
        '<option value="">Select error type</option>' +
        renderErrorOptions(part.error_type) +
        "</select>" +
        "</div>" +
        "</div>";
    }

    return '<article class="part-card">' +
      '<div class="part-meta">' +
      '<span class="part-id">' + escapeHtml(part.part_id) + "</span>" +
      '<span class="part-text">' + escapeHtml(part.text) + "</span>" +
      '<span class="part-type">' + escapeHtml(part.type) + "</span>" +
      "</div>" +
      '<div class="field-grid">' +
      '<div class="field-group">' +
      '<div class="field-title">Decomposition Quality</div>' +
      '<div class="option-row">' + renderRadioGroup(part, "decomp_quality") + "</div>" +
      "</div>" +
      '<div class="field-group">' +
      '<div class="field-title">Correctness</div>' +
      '<div class="option-row">' + renderRadioGroup(part, "correctness") + "</div>" +
      "</div>" +
      '<div class="field-group">' +
      '<div class="field-title">Importance</div>' +
      '<p class="helper-text">How important is this part for the overall meaning of the caption?</p>' +
      '<div class="option-row">' + renderRadioGroup(part, "severity") + "</div>" +
      "</div>" +
      errorMarkup +
      "</div>" +
      "</article>";
  }

  function render() {
    clampIndex();
    if (!samples.length) {
      dom.progressText.textContent = "No samples loaded";
      dom.samplePanel.innerHTML = '<div class="empty-state">Dataset is empty.</div>';
      setNavDisabled(true);
      return;
    }

    var sample = currentSample();
    var annotation = currentAnnotation();
    dom.progressText.textContent = "Sample " + (state.currentIndex + 1) + " / " + samples.length +
      " | Completed " + completedAnnotations().length + " / " + samples.length;

    var cards = "";
    for (var i = 0; i < annotation.parts.length; i += 1) {
      cards += renderPartCard(annotation.parts[i]);
    }

    dom.samplePanel.innerHTML =
      '<div class="sample-grid">' +
      '<div class="media-column">' +
      '<div class="caption-box">' +
      '<p class="caption-label">Caption</p>' +
      '<p class="caption-text">' + escapeHtml(sample.caption) + "</p>" +
      "</div>" +
      '<div class="image-frame">' +
      '<img id="sampleImage" src="' + IMAGE_DIR + "/" + encodeURIComponent(sample.image_file) + '" alt="' + escapeHtml(sample.caption) + '">' +
      "</div>" +
      "</div>" +
      '<div class="annotation-column">' +
      '<section class="parts-panel">' +
      '<div class="parts-header">' +
      "<h2>Semantic Parts</h2>" +
      '<span class="part-count">' + annotation.parts.length + " parts</span>" +
      "</div>" +
      '<div class="parts-list">' + (cards || '<div class="empty-state">No parts extracted.</div>') + "</div>" +
      "</section>" +
      '<section class="score-panel">' +
      '<p class="section-label">Overall Caption Correctness</p>' +
      '<p class="helper-text">How well does this caption describe the image overall?</p>' +
      '<div class="score-options">' + renderOverallOptions(annotation) + "</div>" +
      "</section>" +
      "</div>" +
      "</div>";

    var image = document.getElementById("sampleImage");
    image.onerror = function () {
      showStatus("Image failed to load: images/" + sample.image_file, "error");
    };

    setNavDisabled(false);
    dom.prevBtn.disabled = state.currentIndex === 0;
    dom.nextBtn.disabled = state.currentIndex === samples.length - 1;
  }

  function updateFromInput(target) {
    var annotation = currentAnnotation();
    if (!annotation) {
      return;
    }

    if (target.name === "overall_score") {
      annotation.overall_score = Number(target.value);
      saveState();
      render();
      return;
    }

    var partId = target.getAttribute("data-part-id");
    var field = target.getAttribute("data-field");
    if (!partId || !field) {
      return;
    }

    for (var i = 0; i < annotation.parts.length; i += 1) {
      var part = annotation.parts[i];
      if (part.part_id === partId) {
        if (field === "error_type") {
          part.error_type = target.value || null;
        } else {
          part[field] = target.value;
          if (field === "correctness" && target.value !== "incorrect") {
            part.error_type = null;
          }
        }
        break;
      }
    }

    normalizeAnnotation(annotation);
    saveState();
    render();
  }

  function showValidation(errors) {
    var message = errors.slice(0, 5).join(" ");
    if (errors.length > 5) {
      message += " Plus " + (errors.length - 5) + " more.";
    }
    showStatus(message, "error");
  }

  function saveCurrent() {
    var annotation = currentAnnotation();
    if (!annotation) {
      showStatus("No sample loaded.", "error");
      return false;
    }
    var errors = validate(annotation, true);
    if (errors.length) {
      showValidation(errors);
      return false;
    }
    saveState();
    showStatus("Current sample is complete.", "ok");
    render();
    return true;
  }

  function goPrevious() {
    saveState();
    if (state.currentIndex > 0) {
      state.currentIndex -= 1;
      saveState();
      showStatus("");
      render();
      window.scrollTo(0, 0);
    }
  }

  function goNext() {
    if (!saveCurrent()) {
      return;
    }
    if (state.currentIndex < samples.length - 1) {
      state.currentIndex += 1;
      saveState();
      showStatus("");
      render();
      window.scrollTo(0, 0);
    }
  }

  function exportJson() {
    if (!annotatorId) {
      showStatus("Annotator ID is required before export.", "error");
      return;
    }
    var annotations = completedAnnotations();
    if (!annotations.length) {
      showStatus("No completed annotations are available to export.", "error");
      return;
    }

    var exportedAt = new Date().toISOString();
    var payload = {
      annotator_id: annotatorId,
      dataset: DATASET,
      exported_at: exportedAt,
      annotations: annotations
    };

    var blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "annotations_" + safeId(annotatorId) + "_" + exportedAt.replace(/[:.]/g, "-") + ".json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showStatus("Exported " + annotations.length + " completed annotations.", "ok");
  }

  function resetCurrent() {
    var sample = currentSample();
    if (!sample) {
      return;
    }
    if (!window.confirm("Reset annotations for " + sample.sample_id + "?")) {
      return;
    }
    delete state.annotations[sample.sample_id];
    saveState();
    showStatus("Reset " + sample.sample_id + ".", "ok");
    render();
  }

  function resetAll() {
    if (!annotatorId) {
      showStatus("Annotator ID is required to reset stored progress.", "error");
      return;
    }
    if (!window.confirm('Reset all progress for annotator "' + annotatorId + '"?')) {
      return;
    }
    localStorage.removeItem(storageKey(annotatorId));
    localStorage.removeItem(legacyStorageKey(annotatorId));
    state = emptyState();
    saveState();
    showStatus("All progress reset for this annotator.", "ok");
    render();
  }

  function loadDataset() {
    return fetch(DATA_URL, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Could not load " + DATA_URL + ": HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        if (!Array.isArray(data)) {
          throw new Error(DATA_URL + " must contain a JSON array.");
        }
        samples = data;
      });
  }

  function bindEvents() {
    dom.annotatorId.addEventListener("input", function () {
      var nextId = dom.annotatorId.value.trim();
      if (nextId === annotatorId) {
        return;
      }
      annotatorId = nextId;
      if (annotatorId) {
        localStorage.setItem(LAST_ANNOTATOR_KEY, annotatorId);
      }
      loadStateForAnnotator(annotatorId);
      showStatus("");
      render();
    });

    dom.samplePanel.addEventListener("change", function (event) {
      updateFromInput(event.target);
    });

    dom.exportBtn.addEventListener("click", exportJson);
    dom.resetCurrentBtn.addEventListener("click", resetCurrent);
    dom.resetAllBtn.addEventListener("click", resetAll);
    dom.prevBtn.addEventListener("click", goPrevious);
    dom.saveBtn.addEventListener("click", saveCurrent);
    dom.nextBtn.addEventListener("click", goNext);
  }

  function init() {
    dom.annotatorId = document.getElementById("annotatorId");
    dom.exportBtn = document.getElementById("exportBtn");
    dom.resetCurrentBtn = document.getElementById("resetCurrentBtn");
    dom.resetAllBtn = document.getElementById("resetAllBtn");
    dom.prevBtn = document.getElementById("prevBtn");
    dom.saveBtn = document.getElementById("saveBtn");
    dom.nextBtn = document.getElementById("nextBtn");
    dom.progressText = document.getElementById("progressText");
    dom.statusPanel = document.getElementById("statusPanel");
    dom.samplePanel = document.getElementById("samplePanel");

    bindEvents();
    setNavDisabled(true);

    var lastAnnotator = localStorage.getItem(LAST_ANNOTATOR_KEY) || "";
    if (lastAnnotator) {
      annotatorId = lastAnnotator;
      dom.annotatorId.value = lastAnnotator;
    }

    loadDataset()
      .then(function () {
        loadStateForAnnotator(annotatorId);
        render();
        showStatus("");
      })
      .catch(function (error) {
        dom.progressText.textContent = "Dataset load failed";
        dom.samplePanel.innerHTML = '<div class="empty-state">Could not load <code>data/pilot_decomposed.json</code>.</div>';
        showStatus(error.message, "error");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());

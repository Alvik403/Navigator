(function (global) {
  "use strict";

  var STATUS_RU = { active: "активен", inactive: "не активен" };
  var STRIKE_STATUS_RU = { active: "активен", appealed: "апелляция", revoked: "отменён" };

  var REPORTS = [
    {
      id: "employees",
      title: "Список сотрудников",
      purpose: "Выгрузка данных по ученикам",
      sheetName: "Сотрудники",
      fileName: "report_employees",
      view: "tree",
    },
    {
      id: "attendance_tracks",
      title: "Посещение по трекам",
      purpose: "Аналитика посещаемости",
      sheetName: "Посещение треков",
      fileName: "report_attendance_tracks",
      view: "table",
    },
    {
      id: "strikes",
      title: "Страйки",
      purpose: "Аналитика страйков",
      sheetName: "Страйки",
      fileName: "report_strikes",
      view: "tree",
    },
    {
      id: "employee_tracks",
      title: "Треки сотрудника",
      purpose: "Треки по сотрудникам",
      sheetName: "Треки сотрудников",
      fileName: "report_employee_tracks",
      view: "tree",
    },
    {
      id: "work_tracks",
      title: "Треки обучения",
      purpose: "Состав по трекам",
      sheetName: "Треки",
      fileName: "report_work_tracks",
      view: "tree",
    },
    {
      id: "curators",
      title: "Кураторы",
      purpose: "Подопечные по кураторам",
      sheetName: "Кураторы",
      fileName: "report_curators",
      view: "tree",
    },
  ];

  function fmtName(row) {
    return [row.last_name || row.lastName, row.first_name || row.firstName, row.middle_name || row.middleName]
      .filter(Boolean)
      .join(" ");
  }

  function fmtDateShort(value) {
    if (!value) return "—";
    return new Date(value).toLocaleDateString("ru-RU");
  }

  function fmtPhone(phone, HrFields) {
    if (!phone) return "—";
    if (HrFields && HrFields.formatPhoneDisplay) {
      return HrFields.formatPhoneDisplay(phone) || phone;
    }
    return phone;
  }

  function pctNum(part, total) {
    if (!total) return 0;
    return Math.round((part / total) * 100);
  }

  function pct(part, total) {
    if (!total) return "—";
    return pctNum(part, total) + "%";
  }

  function colWidth(headers, rows, keyIdx) {
    var max = String(headers[keyIdx] || "").length;
    rows.forEach(function (row) {
      var len = String(row[keyIdx] == null ? "" : row[keyIdx]).length;
      if (len > max) max = len;
    });
    return Math.min(Math.max(max + 2, 10), 48);
  }

  function buildStyledWorkbook(meta, headers, rows) {
    if (!global.XLSX) throw new Error("Библиотека XLSX не загружена");
    var aoa = [
      [meta.title || "Отчёт"],
      ["Сформировано: " + new Date().toLocaleString("ru-RU")],
    ];
    if (meta.purpose) aoa.push(["Назначение: " + meta.purpose]);
    if (meta.hrName) aoa.push(["HR: " + meta.hrName]);
    aoa.push(["Записей: " + rows.length], [], headers);
    rows.forEach(function (row) { aoa.push(row); });

    var ws = global.XLSX.utils.aoa_to_sheet(aoa);
    ws["!cols"] = headers.map(function (_, i) { return { wch: colWidth(headers, rows, i) }; });
    ws["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: Math.max(headers.length - 1, 0) } }];

    var wb = global.XLSX.utils.book_new();
    global.XLSX.utils.book_append_sheet(wb, ws, (meta.sheetName || "Отчёт").slice(0, 31));
    return wb;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function branchOpen(expanded, id) {
    if (expanded[id] === true) return true;
    if (expanded[id] === false) return false;
    return false;
  }

  function isNestedBranch(child) {
    return !!(child && (child.branch || (child.id && Array.isArray(child.children))));
  }

  function renderLeafLi(child) {
    var fieldsHtml = (child.fields || []).map(function (f) {
      return '<span class="report-field"><em>' + escapeHtml(f.label) + "</em> " + escapeHtml(f.value) + "</span>";
    }).join("");
    return '<li class="report-leaf">' +
      '<div class="report-leaf-head">' +
      '<span class="report-leaf-title">' + escapeHtml(child.title) + "</span>" +
      renderTags(child.tags) +
      "</div>" +
      (fieldsHtml ? '<div class="report-leaf-fields">' + fieldsHtml + "</div>" : "") +
      "</li>";
  }

  function renderBranchBlock(node, expanded, nested) {
    var open = branchOpen(expanded, node.id);
    var cls = "report-branch" + (nested ? " report-branch-nested" : "");
    var bodyHtml = renderBranchBody(node.children || [], expanded);
    return '<details class="' + cls + '" data-branch-id="' + escapeHtml(node.id) + '"' + (open ? " open" : "") + ">" +
      '<summary class="report-branch-head">' +
      '<span class="report-chevron" aria-hidden="true"></span>' +
      '<span class="report-branch-title">' + escapeHtml(node.title) + "</span>" +
      (node.meta ? '<span class="report-branch-meta">' + escapeHtml(node.meta) + "</span>" : "") +
      renderTags(node.tags) +
      '<span class="report-branch-badge">' + escapeHtml(node.badge || "") + "</span>" +
      "</summary>" +
      bodyHtml +
      "</details>";
  }

  function renderBranchBody(children, expanded) {
    if (!children.length) {
      return '<div class="report-branch-body"><div class="nested-empty">Нет записей</div></div>';
    }
    var parts = [];
    var leafBuffer = [];
    children.forEach(function (child) {
      if (isNestedBranch(child)) {
        if (leafBuffer.length) {
          parts.push('<ul class="report-leaf-list">' + leafBuffer.join("") + "</ul>");
          leafBuffer = [];
        }
        parts.push(renderBranchBlock(child, expanded, true));
      } else {
        leafBuffer.push(renderLeafLi(child));
      }
    });
    if (leafBuffer.length) {
      parts.push('<ul class="report-leaf-list">' + leafBuffer.join("") + "</ul>");
    }
    return '<div class="report-branch-body">' + parts.join("") + "</div>";
  }

  function renderTree(tree, expanded) {
    if (!tree || !tree.length) {
      return '<div class="empty">Нет данных для отображения</div>';
    }
    return '<div class="report-tree">' + tree.map(function (branch) {
      return renderBranchBlock(branch, expanded, false);
    }).join("") + "</div>";
  }

  function buildEmployeesReport(ctx) {
    var D = ctx.D;
    var HrFields = ctx.HrFields;
    var headers = ["Трек", "Фамилия", "Имя", "Отчество", "ID MAX", "Телефон", "Куратор", "Страйки", "Статус"];
    var buckets = {};
    D.usersByRole("student").forEach(function (u) {
      var tracks = D.studentTracks(u.id);
      var keys = tracks.length ? tracks.map(function (t) { return t.name; }) : ["Без трека"];
      keys.forEach(function (key) {
        if (!buckets[key]) buckets[key] = [];
        if (!buckets[key].some(function (x) { return x.id === u.id; })) buckets[key].push(u);
      });
    });
    var tree = Object.keys(buckets).sort(function (a, b) {
      if (a === "Без трека") return 1;
      if (b === "Без трека") return -1;
      return a.localeCompare(b, "ru");
    }).map(function (name) {
      var list = buckets[name];
      return {
        id: "grp-" + name,
        title: name,
        badge: list.length + " чел.",
        children: list.map(function (u) {
          var curator = D.userById(u.id_curator);
          return {
            title: D.fullName(u),
            tags: [
              u.id_max ? "MAX " + u.id_max : null,
              STATUS_RU[u.status] || u.status,
              (u.strikes || 0) ? "страйки " + u.strikes + "/3" : null,
            ].filter(Boolean),
            fields: [
              { label: "Телефон", value: fmtPhone(u.phone, HrFields) },
              { label: "Куратор", value: curator ? D.fullName(curator) : "—" },
            ],
            _user: u,
          };
        }),
      };
    });
    var rows = [];
    tree.forEach(function (branch) {
      branch.children.forEach(function (child) {
        var u = child._user;
        if (!u) return;
        var curator = D.userById(u.id_curator);
        rows.push([
          branch.title,
          u.lastName,
          u.firstName,
          u.middleName || "",
          u.id_max || "",
          fmtPhone(u.phone, HrFields),
          curator ? D.fullName(curator) : "—",
          String(u.strikes || 0),
          STATUS_RU[u.status] || u.status,
        ]);
      });
    });
    return { view: "tree", tree: tree, headers: headers, rows: rows };
  }

  function buildEmployeeTracksReport(ctx) {
    var D = ctx.D;
    var headers = ["Сотрудник", "Трек", "Статус"];
    var tree = D.usersByRole("student").map(function (u) {
      var tracks = D.studentTracks(u.id);
      return {
        id: "emp-" + u.id,
        title: D.fullName(u),
        badge: tracks.length ? tracks.length + " треков" : "без треков",
        children: tracks.length ? tracks.map(function (t) {
          return {
            title: t.name,
            tags: [STATUS_RU[u.status] || u.status],
            fields: [{ label: "Код", value: t.code || "—" }],
          };
        }) : [{
          title: "Не назначен на трек",
          tags: [STATUS_RU[u.status] || u.status],
          fields: [],
        }],
      };
    }).sort(function (a, b) { return a.title.localeCompare(b.title, "ru"); });

    var rows = [];
    tree.forEach(function (branch) {
      branch.children.forEach(function (child) {
        rows.push([
          branch.title,
          child.title,
          (child.tags && child.tags[0]) || "",
        ]);
      });
    });
    return { view: "tree", tree: tree, headers: headers, rows: rows };
  }

  function buildWorkTracksReport(ctx) {
    var D = ctx.D;
    var HrFields = ctx.HrFields;
    var headers = ["Трек", "Участник", "Статус", "Телефон"];
    var tracks = D.tracks();
    var tree = tracks.map(function (t) {
      var students = (D.trackAssignments(t.id) || [])
        .filter(function (a) { return (a.status || "active") === "active"; })
        .map(function (a) { return D.userById(a.user_id); })
        .filter(Boolean);
      return {
        id: "tr-" + t.id,
        title: t.name,
        badge: students.length + " уч.",
        tags: [t.code || ""],
        children: students.length ? students.map(function (u) {
          return {
            title: D.fullName(u),
            tags: [STATUS_RU[u.status] || u.status],
            fields: [{ label: "Телефон", value: fmtPhone(u.phone, HrFields) }],
            _user: u,
          };
        }) : [{ title: "Нет участников", tags: [], fields: [], _empty: true }],
      };
    });
    var rows = [];
    tree.forEach(function (branch) {
      (branch.children || []).forEach(function (child) {
        if (child._empty) {
          rows.push([branch.title, "—", "—", "—"]);
          return;
        }
        rows.push([
          branch.title,
          child.title,
          (child.tags && child.tags[0]) || "",
          child.fields && child.fields[0] ? child.fields[0].value : "—",
        ]);
      });
    });
    return { view: "tree", tree: tree, headers: headers, rows: rows };
  }

  function buildCuratorsReport(ctx) {
    var D = ctx.D;
    var HrFields = ctx.HrFields;
    var headers = ["Куратор", "Подопечный", "Телефон", "Треки"];
    var tree = D.usersByRole("curator").map(function (c) {
      var wards = D.usersByRole("student").filter(function (u) { return u.id_curator === c.id; });
      return {
        id: "cur-" + c.id,
        title: D.fullName(c),
        badge: wards.length ? wards.length + " подопечных" : "нет подопечных",
        meta: fmtPhone(c.phone, HrFields),
        children: wards.length ? wards.map(function (u) {
          var trackNames = D.studentTracks(u.id).map(function (t) { return t.name; }).join(", ");
          return {
            title: D.fullName(u),
            tags: [u.phone ? "есть телефон" : "без телефона"],
            fields: [
              { label: "Телефон", value: fmtPhone(u.phone, HrFields) },
              { label: "Треки", value: trackNames || "—" },
            ],
          };
        }) : [{ title: "Нет подопечных", tags: [], fields: [], _empty: true }],
      };
    }).sort(function (a, b) { return a.title.localeCompare(b.title, "ru"); });

    var rows = [];
    tree.forEach(function (branch) {
      branch.children.forEach(function (child) {
        if (child._empty) return;
        rows.push([
          branch.title,
          child.title,
          child.fields && child.fields[0] ? child.fields[0].value : "—",
          child.fields && child.fields[1] ? child.fields[1].value : "—",
        ]);
      });
    });
    return { view: "tree", tree: tree, headers: headers, rows: rows };
  }

  async function buildAttendanceTracksReport(ctx) {
    var data = await ctx.api.get("/hr/reports/attendance/tracks");
    var items = data.items || [];
    var headers = ["Трек", "Всего", "Был", "Опоздал", "Не был", "%"];
    var rows = items.map(function (r) {
      var attended = (r.present_count || 0) + (r.late_count || 0);
      return [
        r.track_name || r.group_name || "—",
        String(r.marks_total || 0),
        String(r.present_count || 0),
        String(r.late_count || 0),
        String(r.absent_count || 0),
        pct(attended, r.marks_total || 0),
      ];
    });
    return {
      view: "table",
      headers: headers,
      rows: rows,
      bars: items.map(function (r) {
        var attended = (r.present_count || 0) + (r.late_count || 0);
        return { pct: pctNum(attended, r.marks_total || 0) };
      }),
    };
  }

  async function buildStrikesReport(ctx) {
    var data = await ctx.api.get("/hr/strikes");
    var items = data.items || [];
    var headers = ["ФИО", "Трек", "№", "Статус", "Причина", "Дата"];
    var byTrack = {};
    items.forEach(function (s) {
      var key = s.track_name || s.group_name || "Без трека";
      if (!byTrack[key]) byTrack[key] = [];
      byTrack[key].push(s);
    });
    var tree = Object.keys(byTrack).sort(function (a, b) { return a.localeCompare(b, "ru"); }).map(function (trackName) {
      var list = byTrack[trackName];
      return {
        id: "str-" + trackName,
        title: trackName,
        badge: list.length + " страйков",
        children: list.map(function (s) {
          return {
            title: fmtName(s),
            tags: ["№" + s.strike_number, STRIKE_STATUS_RU[s.status] || s.status],
            fields: [
              { label: "Причина", value: s.reason || "—" },
              { label: "Дата", value: fmtDateShort(s.created_at) },
            ],
          };
        }),
      };
    });
    var rows = items.map(function (s) {
      return [
        fmtName(s),
        s.track_name || s.group_name || "—",
        String(s.strike_number || ""),
        STRIKE_STATUS_RU[s.status] || s.status,
        s.reason || "",
        fmtDateShort(s.created_at),
      ];
    });
    return { view: "tree", tree: tree, headers: headers, rows: rows };
  }

  async function loadReport(reportId, ctx) {
    var meta = REPORTS.find(function (r) { return r.id === reportId; });
    if (!meta) throw new Error("Неизвестный отчёт");

    var payload;
    if (reportId === "employees") payload = buildEmployeesReport(ctx);
    else if (reportId === "employee_tracks") payload = buildEmployeeTracksReport(ctx);
    else if (reportId === "work_tracks") payload = buildWorkTracksReport(ctx);
    else if (reportId === "curators") payload = buildCuratorsReport(ctx);
    else if (reportId === "attendance_tracks") payload = await buildAttendanceTracksReport(ctx);
    else if (reportId === "strikes") payload = await buildStrikesReport(ctx);
    else throw new Error("Отчёт не реализован");

    return {
      meta: meta,
      view: payload.view || meta.view || "table",
      tree: payload.tree || null,
      headers: payload.headers,
      rows: payload.rows,
      bars: payload.bars || null,
    };
  }

  function exportReport(result, ctx) {
    var wb = buildStyledWorkbook({
      title: result.meta.title,
      purpose: result.meta.purpose,
      sheetName: result.meta.sheetName,
      hrName: ctx.hrName,
    }, result.headers, result.rows);
    global.XLSX.writeFile(wb, result.meta.fileName + "_" + new Date().toISOString().slice(0, 10) + ".xlsx");
  }

  function renderTags(tags) {
    if (!tags || !tags.length) return "";
    return '<span class="report-tags">' + tags.map(function (t) {
      return '<span class="report-tag">' + escapeHtml(t) + "</span>";
    }).join("") + "</span>";
  }

  function renderPreviewTable(result) {
    var headers = result.headers;
    var rows = result.rows;
    if (!rows.length) {
      return '<div class="empty">Нет данных для отображения</div>';
    }
    var head = headers.map(function (h) { return "<th>" + escapeHtml(h) + "</th>"; }).join("");
    var body = rows.map(function (row, ri) {
      return "<tr>" + row.map(function (cell, ci) {
        if (result.bars && ci === headers.length - 1) {
          var p = result.bars[ri] ? result.bars[ri].pct : 0;
          return '<td class="report-bar-cell"><div class="report-bar-wrap"><div class="report-bar" style="width:' + p + '%"></div></div><span class="report-bar-label">' + p + "%</span></td>";
        }
        return "<td>" + escapeHtml(cell == null || cell === "" ? "—" : cell) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<div class="table-wrap report-preview-table"><table class="report-table"><thead><tr>' + head + '</tr></thead><tbody>' + body + "</tbody></table></div>";
  }

  function renderPreview(result, expanded) {
    if (!result) return "";
    if (result.view === "tree" && result.tree && result.tree.length) {
      return renderTree(result.tree, expanded || {});
    }
    return renderPreviewTable(result);
  }

  function bindTreeState(container, expanded) {
    if (!container) return;
    container.querySelectorAll("details.report-branch").forEach(function (el) {
      el.addEventListener("toggle", function () {
        expanded[el.dataset.branchId] = el.open;
      });
    });
  }

  function collapseAll(container, expanded) {
    if (!container || !expanded) return;
    container.querySelectorAll("details.report-branch").forEach(function (el) {
      el.open = false;
      if (el.dataset.branchId) expanded[el.dataset.branchId] = false;
    });
  }

  global.HrReports = {
    catalog: REPORTS,
    load: loadReport,
    export: exportReport,
    renderPreview: renderPreview,
    bindTreeState: bindTreeState,
    collapseAll: collapseAll,
  };
})(window);

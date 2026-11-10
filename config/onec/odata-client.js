#!/usr/bin/env node
/**
 * Общий клиент прямого доступа к 1С по OData (без зависимостей, Node >= 18).
 *
 * Используется скриптами Skills. Конфиг: config/onec-config.json
 * (переопределяется переменной ONEC_CONFIG). Переменные окружения
 * ODATA_BASE_URL / ODATA_USERNAME / ODATA_PASSWORD / ONEC_DATABASE
 * имеют приоритет над значениями из файла.
 *
 * Экспорт:
 *   loadConfig()                      → { databases, defaultDatabase, defaults, safety }
 *   client(database?)                 → { req, BASE, db, defaults, safety }
 *   req(method, url, data)            → { status, body }  (body — строка)
 *   rows(body)                        → массив value из JSON-ответа
 *   obj(body)                         → разобранный JSON
 *   parseError(status, body)          → { code, message } из odata.error или null
 *
 * Важные соглашения 1С OData 3.0 (проверено на практике):
 *   - ко всем URL добавлять ?$format=json, иначе вернётся XML;
 *   - ключ объекта в пути: EntitySet(guid'xxx-...') — кавычки внутри guid обязательны;
 *   - фильтры: substringof('текст', Поле), Поле eq 'значение'; contains/tolower НЕ поддержаны;
 *   - $expand с кириллическими именами возвращает 501 — табличные части читать отдельным запросом;
 *   - даты документов отправлять как "YYYY-MM-DDT00:00:00" (без Z);
 *   - POST нового документа/элемента возвращает 201 и присвоенные Number/Code.
 */

"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");

/** Поиск файла конфигурации: ONEC_CONFIG → ./config/onec-config.json → рядом со скриптом. */
function findConfigFile() {
  if (process.env.ONEC_CONFIG) return process.env.ONEC_CONFIG;
  const candidates = [
    path.join(process.cwd(), "config", "onec-config.json"),
    path.join(__dirname, "..", "onec-config.json"),
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

function loadConfig() {
  const file = findConfigFile();
  if (!file) {
    throw new Error(
      "Не найден config/onec-config.json. Задайте ONEC_CONFIG или запустите скрипт из корня проекта."
    );
  }
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

/** Клиент для конкретной базы. */
function client(databaseName) {
  const cfg = loadConfig();
  const dbName = databaseName || process.env.ONEC_DATABASE || cfg.defaultDatabase;
  const db = cfg.databases && cfg.databases[dbName];
  if (!db) {
    throw new Error(
      `База «${dbName}» не описана в config/onec-config.json (доступны: ${Object.keys(cfg.databases || {}).join(", ")})`
    );
  }
  const BASE = (
    process.env.ODATA_BASE_URL || db.odataBaseUrl || ""
  ).replace(/\/?$/, "/");
  const username = process.env.ODATA_USERNAME || (db.auth && db.auth.username) || "";
  const password = process.env.ODATA_PASSWORD || (db.auth && db.auth.password) || "";
  if (!BASE || !username) throw new Error("ODATA_BASE_URL/ODATA_USERNAME не заданы (config/onec-config.json или env)");
  const auth = "Basic " + Buffer.from(username + ":" + password).toString("base64");

  function req(method, url, data) {
    return new Promise((resolve, reject) => {
      const u = new URL(url);
      const options = {
        hostname: u.hostname,
        port: u.port || (u.protocol === "https:" ? 443 : 80),
        path: u.pathname + u.search,
        method,
        headers: { Authorization: auth, Accept: "application/json" },
      };
      if (data !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.headers["Content-Length"] = Buffer.byteLength(JSON.stringify(data));
      }
      const r = http.request(options, (res) => {
        let d = "";
        res.on("data", (c) => (d += c));
        res.on("end", () => resolve({ status: res.statusCode, body: d }));
      });
      r.on("error", reject);
      if (data !== undefined) r.write(JSON.stringify(data));
      r.end();
    });
  }

  return {
    req,
    BASE,
    db: dbName,
    defaults: cfg.defaults || {},
    safety: cfg.safety || {},
    cfg,
  };
}

function obj(body) {
  return JSON.parse(body);
}
function rows(body) {
  return JSON.parse(body).value || [];
}

/** Разбор ошибки 1С: { "odata.error": { code, message: { value } } }. */
function parseError(status, body) {
  try {
    const j = JSON.parse(body);
    if (j && j["odata.error"]) {
      return {
        code: j["odata.error"].code,
        message: (j["odata.error"].message && j["odata.error"].message.value) || "без описания",
      };
    }
  } catch (_) {
    /* не JSON — вероятно HTML-страница (например, 404 веб-сервера) */
  }
  return null;
}

/** Дата документа для payload: только дата, без времени и Z. */
function docDate(yyyy_mm_dd) {
  const d = yyyy_mm_dd ? new Date(yyyy_mm_dd) : new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T00:00:00`;
}

module.exports = { loadConfig, client, req: null, obj, rows, parseError, docDate };

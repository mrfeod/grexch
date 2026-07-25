const RESULTS_URL =
  "https://www.greek-language.gr/certification/results/index.html";

function decodeEntities(text) {
  const named = {
    amp: "&",
    apos: "'",
    gt: ">",
    lt: "<",
    nbsp: " ",
    quot: '"',
  };

  return text.replace(
    /&(#x[\da-f]+|#\d+|amp|apos|gt|lt|nbsp|quot);/gi,
    (entity, value) => {
      if (value[0] !== "#") {
        return named[value.toLowerCase()] ?? entity;
      }

      const hexadecimal = value[1].toLowerCase() === "x";
      const codePoint = Number.parseInt(value.slice(hexadecimal ? 2 : 1), hexadecimal ? 16 : 10);

      try {
        return String.fromCodePoint(codePoint);
      } catch {
        return entity;
      }
    },
  );
}

export function htmlToText(html) {
  return decodeEntities(
    html
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, "")
      .replace(/<img\b[^>]*checkon\.png[^>]*>/gi, " ✓")
      .replace(/<img\b[^>]*>/gi, "")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(?:h[1-6]|p|tr|table|div|li)>/gi, "\n")
      .replace(/<\/(?:b|strong)>/gi, " ")
      .replace(/<\/t[dh]>\s*<t[dh]\b[^>]*>/gi, " ")
      .replace(/<[^>]+>/g, ""),
  )
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter(Boolean)
    .join("\n")
    .trim();
}

function textResponse(body, status = 200) {
  return new Response(`${body}\n`, {
    status,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

export default {
  async fetch(request) {
    if (request.method !== "GET") {
      return textResponse("Метод не поддерживается. Используйте GET.", 405);
    }

    const url = new URL(request.url);
    const centerCode = url.searchParams.get("center")?.trim();
    const candidateCode = url.searchParams.get("code")?.trim();
    const candidateSurname = url.searchParams.get("surname")?.trim().toUpperCase();

    if (!centerCode || !candidateCode || !candidateSurname) {
      return textResponse(
        "Укажите параметры: ?center=КОД_ЦЕНТРА&code=КОД_КАНДИДАТА&surname=ФАМИЛИЯ",
        400,
      );
    }

    const form = new URLSearchParams({
      inputCenterCode: centerCode,
      inputCandidateCode: candidateCode,
      inputCandidateSurname: candidateSurname,
    });

    let upstream;
    try {
      upstream = await fetch(RESULTS_URL, {
        method: "POST",
        headers: {
          "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
          "user-agent": "Mozilla/5.0 (compatible; GreekResultsWorker/1.0)",
        },
        body: form,
      });
    } catch (error) {
      return textResponse(`Ошибка запроса к сайту результатов: ${error.message}`, 502);
    }

    if (!upstream.ok) {
      return textResponse(
        `Сайт результатов вернул ошибку HTTP ${upstream.status}.`,
        502,
      );
    }

    const html = await upstream.text();

    const result = htmlToText(html);
    if (!result) {
      return textResponse("Сайт результатов вернул пустой ответ.", 502);
    }

    return textResponse(
      `Проверка: ${centerCode}-${candidateCode}-${candidateSurname}\n\n${result}`,
    );
  },
};

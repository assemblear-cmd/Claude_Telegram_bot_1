import "dotenv/config";
import { Bot, InputFile, InputMediaBuilder, InlineKeyboard } from "grammy";
import { GoogleGenAI, Modality } from "@google/genai";

const THINKING_MODEL = "gemini-3.1-flash-image-preview";
const IMAGE_MODEL = "gemini-3.1-flash-image-preview";
const DEFAULT_COUNT = 1;
const MAX_COUNT = 10;

const userCounts = new Map<number, number>();

// Project storage: userId -> { name -> { imageBuffer, lastPrompt } }
interface Project {
  imageBuffer: Buffer;
  lastPrompt: string;
  savedAt: Date;
}
const userProjects = new Map<number, Map<string, Project>>();

// Last generated image per user (for reply-based iteration)
interface LastResult {
  imageBuffer: Buffer;
  prompt: string;
}
const userLastResults = new Map<number, LastResult>();

// Pending save: userId -> true (waiting for project name)
const pendingSave = new Set<number>();

const bot = new Bot(process.env.BOT_TOKEN!);
const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });

// --- Keyboards ---

function mainMenuKeyboard(): InlineKeyboard {
  return new InlineKeyboard()
    .text("📂 Мои проекты", "menu:projects")
    .text("🔢 Кол-во вариантов", "menu:count")
    .row()
    .text("❓ Помощь", "menu:help");
}

function postGenerationKeyboard(): InlineKeyboard {
  return new InlineKeyboard()
    .text("💾 Сохранить", "action:save")
    .text("🔄 Ещё варианты", "action:more")
    .row()
    .text("🔢 Изменить кол-во", "menu:count")
    .text("📂 Проекты", "menu:projects");
}

function countKeyboard(currentCount: number): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (let i = 1; i <= 5; i++) {
    kb.text(i === currentCount ? `[${i}]` : `${i}`, `count:${i}`);
  }
  kb.row();
  for (let i = 6; i <= 10; i++) {
    kb.text(i === currentCount ? `[${i}]` : `${i}`, `count:${i}`);
  }
  kb.row().text("⬅️ Назад", "menu:main");
  return kb;
}

function projectsKeyboard(projects: Map<string, Project>): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (const [name] of projects) {
    kb.text(`📁 ${name}`, `project:load:${name}`).row();
  }
  kb.text("⬅️ Назад", "menu:main");
  return kb;
}

function projectActionsKeyboard(name: string): InlineKeyboard {
  return new InlineKeyboard()
    .text("📂 Загрузить", `project:load:${name}`)
    .text("🗑 Удалить", `project:confirmdelete:${name}`)
    .row()
    .text("⬅️ К проектам", "menu:projects");
}

function confirmDeleteKeyboard(name: string): InlineKeyboard {
  return new InlineKeyboard()
    .text("✅ Да, удалить", `project:delete:${name}`)
    .text("❌ Отмена", "menu:projects");
}

function helpText(): string {
  return (
    "📖 Как пользоваться ботом:\n\n" +
    "📷 Отправьте фото с подписью — начать новый дизайн\n" +
    "↩️ Ответьте на результат с новым описанием — итерация\n" +
    "💬 Просто напишите текст — продолжить последний дизайн\n\n" +
    "Подсказки:\n" +
    "• Можно писать «3 современный дом» — цифра в начале задаёт кол-во вариантов\n" +
    "• Ответьте на конкретную картинку, чтобы итерировать именно её"
  );
}

// --- Core functions ---

function parseCount(text: string): { count: number; prompt: string } {
  const match = text.match(/^(\d+)\s+(.+)$/s);
  if (match) {
    const n = parseInt(match[1], 10);
    if (n >= 1 && n <= MAX_COUNT) {
      return { count: n, prompt: match[2] };
    }
  }
  return { count: 0, prompt: text };
}

async function enhancePrompt(userPrompt: string): Promise<string> {
  const response = await ai.models.generateContent({
    model: THINKING_MODEL,
    contents: [
      {
        role: "user",
        parts: [
          {
            text: `You are an expert prompt engineer for architectural image generation.
Take the user's description and create a detailed, English prompt optimized for image generation.
Focus on: materials, lighting, camera angle, atmosphere, style.
Keep it under 200 words. Return ONLY the prompt, no explanations.

User description: ${userPrompt}`,
          },
        ],
      },
    ],
  });

  const text = response.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) throw new Error("No response from thinking model");
  console.log(`[${THINKING_MODEL}] Enhanced prompt: ${text.substring(0, 100)}...`);
  return text;
}

async function generateImage(
  imageBuffer: Buffer,
  enhancedPrompt: string
): Promise<Buffer> {
  const base64Image = imageBuffer.toString("base64");

  const response = await ai.models.generateContent({
    model: IMAGE_MODEL,
    contents: [
      {
        role: "user",
        parts: [
          {
            inlineData: {
              mimeType: "image/jpeg",
              data: base64Image,
            },
          },
          { text: enhancedPrompt },
        ],
      },
    ],
    config: {
      responseModalities: [Modality.IMAGE, Modality.TEXT],
    },
  });

  console.log(`[${IMAGE_MODEL}] Generation complete`);

  const parts = response.candidates?.[0]?.content?.parts;
  if (parts) {
    for (const part of parts) {
      if (part.inlineData?.data) {
        return Buffer.from(part.inlineData.data, "base64");
      }
    }
  }

  throw new Error("No image in Gemini response");
}

async function generateWithRetry(
  imageBuffer: Buffer,
  enhancedPrompt: string
): Promise<Buffer | null> {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      return await generateImage(imageBuffer, enhancedPrompt);
    } catch (err) {
      console.error(`Generation attempt ${attempt} failed:`, err);
      if (attempt === 2) return null;
    }
  }
  return null;
}

async function downloadTelegramPhoto(ctx: any, photo: any): Promise<Buffer> {
  const file = await ctx.api.getFile(photo.file_id);
  const fileUrl = `https://api.telegram.org/file/bot${process.env.BOT_TOKEN!}/${file.file_path}`;
  const response = await fetch(fileUrl);
  return Buffer.from(await response.arrayBuffer());
}

async function runGeneration(
  ctx: any,
  imageBuffer: Buffer,
  prompt: string,
  count: number
): Promise<void> {
  let enhancedPrompt: string;
  try {
    enhancedPrompt = await enhancePrompt(prompt);
  } catch (err) {
    console.error("Prompt enhancement failed:", err);
    await ctx.reply("Ошибка при обработке промпта. Попробуйте ещё раз.");
    return;
  }

  const results = await Promise.all(
    Array.from({ length: count }, () => generateWithRetry(imageBuffer, enhancedPrompt))
  );

  const successful = results.filter((b): b is Buffer => b !== null);

  if (successful.length === 0) {
    await ctx.reply("Не удалось сгенерировать ни одного изображения. Попробуйте позже.");
    return;
  }

  // Save last result for iteration
  const userId = ctx.from!.id;
  userLastResults.set(userId, {
    imageBuffer: successful[0],
    prompt,
  });

  if (successful.length === 1) {
    await ctx.replyWithPhoto(new InputFile(successful[0], "result.png"), {
      caption: "Готово! Ответьте на это фото с новым описанием для итерации.",
      reply_markup: postGenerationKeyboard(),
    });
  } else {
    const media = successful.map((buf, i) =>
      InputMediaBuilder.photo(new InputFile(buf, `result_${i + 1}.png`))
    );
    media[0] = InputMediaBuilder.photo(
      new InputFile(successful[0], "result_1.png"),
      { caption: "Готово! Ответьте на любую картинку с новым описанием для итерации." }
    );
    await ctx.replyWithMediaGroup(media);
    // Media groups don't support inline keyboards, so send buttons separately
    await ctx.reply("Что дальше?", { reply_markup: postGenerationKeyboard() });
  }

  if (successful.length < count) {
    await ctx.reply(`Сгенерировано ${successful.length} из ${count} (остальные не удались).`);
  }
}

// --- Commands ---

bot.command("start", async (ctx) => {
  await ctx.reply(
    "👋 Привет! Я бот для генерации архитектурных визуализаций.\n\n" +
    "Отправьте мне фото с описанием — и я создам новый дизайн.\n" +
    "Или выберите действие:",
    { reply_markup: mainMenuKeyboard() }
  );
});

bot.command("menu", async (ctx) => {
  await ctx.reply("Главное меню:", { reply_markup: mainMenuKeyboard() });
});

bot.command("count", async (ctx) => {
  const arg = ctx.match?.trim();
  if (!arg) {
    const current = userCounts.get(ctx.from!.id) ?? DEFAULT_COUNT;
    await ctx.reply(
      `Текущее количество: ${current}\nВыберите новое:`,
      { reply_markup: countKeyboard(current) }
    );
    return;
  }
  const n = parseInt(arg, 10);
  if (isNaN(n) || n < 1 || n > MAX_COUNT) {
    await ctx.reply(`Укажите число от 1 до ${MAX_COUNT}.`);
    return;
  }
  userCounts.set(ctx.from!.id, n);
  await ctx.reply(`Количество генераций установлено: ${n}`, { reply_markup: mainMenuKeyboard() });
});

bot.command("save", async (ctx) => {
  const name = ctx.match?.trim();
  if (!name) {
    const userId = ctx.from!.id;
    const last = userLastResults.get(userId);
    if (!last) {
      await ctx.reply("Нет результата для сохранения. Сначала сгенерируйте изображение.");
      return;
    }
    pendingSave.add(userId);
    await ctx.reply("Введите имя для проекта:");
    return;
  }
  saveProject(ctx, ctx.from!.id, name);
});

bot.command("load", async (ctx) => {
  const name = ctx.match?.trim();
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (!name) {
    if (!projects || projects.size === 0) {
      await ctx.reply("У вас нет сохранённых проектов.", { reply_markup: mainMenuKeyboard() });
    } else {
      await ctx.reply("Выберите проект:", { reply_markup: projectsKeyboard(projects) });
    }
    return;
  }
  if (!projects?.has(name)) {
    await ctx.reply(`Проект «${name}» не найден.`, { reply_markup: mainMenuKeyboard() });
    return;
  }

  await loadProject(ctx, userId, name);
});

bot.command("projects", async (ctx) => {
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (!projects || projects.size === 0) {
    await ctx.reply("У вас нет сохранённых проектов.\nСгенерируйте изображение и нажмите 💾 Сохранить.", {
      reply_markup: mainMenuKeyboard(),
    });
    return;
  }

  await ctx.reply("Ваши проекты:", { reply_markup: projectsKeyboard(projects) });
});

bot.command("delete", async (ctx) => {
  const name = ctx.match?.trim();
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (!name) {
    await ctx.reply("Укажите имя проекта: /delete мой_дом");
    return;
  }
  if (!projects?.has(name)) {
    await ctx.reply(`Проект «${name}» не найден.`);
    return;
  }

  await ctx.reply(`Удалить проект «${name}»?`, { reply_markup: confirmDeleteKeyboard(name) });
});

// --- Helper functions for project operations ---

async function saveProject(ctx: any, userId: number, name: string): Promise<void> {
  const last = userLastResults.get(userId);
  if (!last) {
    await ctx.reply("Нет результата для сохранения. Сначала сгенерируйте изображение.");
    return;
  }
  if (!userProjects.has(userId)) {
    userProjects.set(userId, new Map());
  }
  userProjects.get(userId)!.set(name, {
    imageBuffer: last.imageBuffer,
    lastPrompt: last.prompt,
    savedAt: new Date(),
  });
  await ctx.reply(`✅ Проект «${name}» сохранён!`, { reply_markup: mainMenuKeyboard() });
}

async function loadProject(ctx: any, userId: number, name: string): Promise<void> {
  const projects = userProjects.get(userId);
  const project = projects?.get(name);
  if (!project) {
    await ctx.reply(`Проект «${name}» не найден.`, { reply_markup: mainMenuKeyboard() });
    return;
  }

  userLastResults.set(userId, {
    imageBuffer: project.imageBuffer,
    prompt: project.lastPrompt,
  });

  await ctx.replyWithPhoto(new InputFile(project.imageBuffer, "project.png"), {
    caption: `📁 Проект «${name}» загружен.\nПромпт: ${project.lastPrompt}\n\nОтветьте на это фото с новым описанием для итерации.`,
    reply_markup: postGenerationKeyboard(),
  });
}

// --- Callback query handlers (button presses) ---

bot.callbackQuery("menu:main", async (ctx) => {
  await ctx.answerCallbackQuery();
  await ctx.editMessageText("Главное меню:", { reply_markup: mainMenuKeyboard() });
});

bot.callbackQuery("menu:projects", async (ctx) => {
  await ctx.answerCallbackQuery();
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (!projects || projects.size === 0) {
    await ctx.editMessageText(
      "У вас нет сохранённых проектов.\nСгенерируйте изображение и нажмите 💾 Сохранить.",
      { reply_markup: new InlineKeyboard().text("⬅️ Назад", "menu:main") }
    );
  } else {
    await ctx.editMessageText("Ваши проекты:", { reply_markup: projectsKeyboard(projects) });
  }
});

bot.callbackQuery("menu:count", async (ctx) => {
  await ctx.answerCallbackQuery();
  const current = userCounts.get(ctx.from!.id) ?? DEFAULT_COUNT;
  await ctx.editMessageText(
    `Текущее количество вариантов: ${current}\nВыберите новое:`,
    { reply_markup: countKeyboard(current) }
  );
});

bot.callbackQuery("menu:help", async (ctx) => {
  await ctx.answerCallbackQuery();
  await ctx.editMessageText(helpText(), {
    reply_markup: new InlineKeyboard().text("⬅️ Назад", "menu:main"),
  });
});

// Count selection
bot.callbackQuery(/^count:(\d+)$/, async (ctx) => {
  const n = parseInt(ctx.match![1], 10);
  userCounts.set(ctx.from!.id, n);
  await ctx.answerCallbackQuery(`Установлено: ${n}`);
  await ctx.editMessageText(
    `✅ Количество вариантов: ${n}`,
    { reply_markup: countKeyboard(n) }
  );
});

// Save action from post-generation buttons
bot.callbackQuery("action:save", async (ctx) => {
  await ctx.answerCallbackQuery();
  const userId = ctx.from!.id;
  const last = userLastResults.get(userId);
  if (!last) {
    await ctx.reply("Нет результата для сохранения.");
    return;
  }
  pendingSave.add(userId);
  await ctx.reply("Введите имя для проекта:");
});

// "More variants" action
bot.callbackQuery("action:more", async (ctx) => {
  await ctx.answerCallbackQuery();
  const userId = ctx.from!.id;
  const last = userLastResults.get(userId);
  if (!last) {
    await ctx.reply("Нет изображения для генерации вариантов.");
    return;
  }
  const count = userCounts.get(userId) ?? DEFAULT_COUNT;
  await ctx.reply(`Генерирую ещё ${count > 1 ? count + " вариантов" : "1 вариант"}...`);
  await runGeneration(ctx, last.imageBuffer, last.prompt, count);
});

// Project load
bot.callbackQuery(/^project:load:(.+)$/, async (ctx) => {
  const name = ctx.match![1];
  await ctx.answerCallbackQuery();
  await loadProject(ctx, ctx.from!.id, name);
});

// Project delete confirmation
bot.callbackQuery(/^project:confirmdelete:(.+)$/, async (ctx) => {
  const name = ctx.match![1];
  await ctx.answerCallbackQuery();
  await ctx.editMessageText(`Удалить проект «${name}»?`, {
    reply_markup: confirmDeleteKeyboard(name),
  });
});

// Project delete confirmed
bot.callbackQuery(/^project:delete:(.+)$/, async (ctx) => {
  const name = ctx.match![1];
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (projects?.has(name)) {
    projects.delete(name);
    await ctx.answerCallbackQuery(`Проект «${name}» удалён`);
  } else {
    await ctx.answerCallbackQuery(`Проект не найден`);
  }

  // Show updated projects list
  if (!projects || projects.size === 0) {
    await ctx.editMessageText("У вас нет сохранённых проектов.", {
      reply_markup: new InlineKeyboard().text("⬅️ Назад", "menu:main"),
    });
  } else {
    await ctx.editMessageText("Ваши проекты:", { reply_markup: projectsKeyboard(projects) });
  }
});

// --- Photo handler: new photo with caption ---
bot.on("message:photo", async (ctx) => {
  pendingSave.delete(ctx.from!.id);
  const caption = ctx.message.caption ?? "";
  if (!caption.trim()) {
    await ctx.reply("Отправьте фото с подписью — описанием желаемого результата.");
    return;
  }

  const { count: inlineCount, prompt } = parseCount(caption);
  const count = inlineCount || (userCounts.get(ctx.from!.id) ?? DEFAULT_COUNT);

  await ctx.reply(`Генерирую ${count > 1 ? count + " вариантов" : "изображение"}, подождите...`);

  const photo = ctx.message.photo[ctx.message.photo.length - 1];
  const imageBuffer = await downloadTelegramPhoto(ctx, photo);

  await runGeneration(ctx, imageBuffer, prompt, count);
});

// --- Text handler: reply to bot's image or plain text ---
bot.on("message:text", async (ctx) => {
  const text = ctx.message.text;
  const userId = ctx.from!.id;

  // Handle pending save — user is entering project name
  if (pendingSave.has(userId) && !text.startsWith("/")) {
    pendingSave.delete(userId);
    await saveProject(ctx, userId, text.trim());
    return;
  }

  // Handle reply to bot's photo — iterate on that image
  const reply = ctx.message.reply_to_message;
  if (reply && reply.from?.id === bot.botInfo.id) {
    let imageBuffer: Buffer | null = null;

    // Reply to a single photo
    if (reply.photo) {
      const photo = reply.photo[reply.photo.length - 1];
      imageBuffer = await downloadTelegramPhoto(ctx, photo);
    }

    // If no photo in replied message, fall back to user's last result
    if (!imageBuffer) {
      const last = userLastResults.get(userId);
      if (last) imageBuffer = last.imageBuffer;
    }

    if (imageBuffer) {
      const { count: inlineCount, prompt } = parseCount(text);
      const count = inlineCount || (userCounts.get(userId) ?? DEFAULT_COUNT);
      await ctx.reply(`Итерирую дизайн (${count > 1 ? count + " вариантов" : "1 вариант"})...`);
      await runGeneration(ctx, imageBuffer, prompt, count);
      return;
    }
  }

  // Plain text without reply — use last result if available
  const last = userLastResults.get(userId);
  if (last && !text.startsWith("/")) {
    const { count: inlineCount, prompt } = parseCount(text);
    const count = inlineCount || (userCounts.get(userId) ?? DEFAULT_COUNT);
    await ctx.reply(`Продолжаю работу над последним дизайном (${count > 1 ? count + " вариантов" : "1 вариант"})...`);
    await runGeneration(ctx, last.imageBuffer, prompt, count);
    return;
  }

  // No context — show menu
  await ctx.reply(
    "Отправьте фото с описанием, чтобы начать.\nИли выберите действие:",
    { reply_markup: mainMenuKeyboard() }
  );
});

bot.catch((err) => {
  console.error("Bot error:", err);
});

bot.start();
console.log(`Bot is running...`);
console.log(`Thinking model: ${THINKING_MODEL}`);
console.log(`Image model: ${IMAGE_MODEL}`);

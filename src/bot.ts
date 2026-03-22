import "dotenv/config";
import { Bot, InputFile, InputMediaBuilder } from "grammy";
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

const bot = new Bot(process.env.BOT_TOKEN!);
const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });

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
      caption: "Ответьте на это сообщение с новым описанием, чтобы продолжить работу над дизайном.",
    });
  } else {
    const media = successful.map((buf, i) =>
      InputMediaBuilder.photo(new InputFile(buf, `result_${i + 1}.png`))
    );
    media[0] = InputMediaBuilder.photo(
      new InputFile(successful[0], "result_1.png"),
      { caption: "Ответьте на любую картинку с новым описанием, чтобы продолжить." }
    );
    await ctx.replyWithMediaGroup(media);
  }

  if (successful.length < count) {
    await ctx.reply(`Сгенерировано ${successful.length} из ${count} (остальные не удались).`);
  }
}

// --- Commands ---

bot.command("count", async (ctx) => {
  const arg = ctx.match?.trim();
  if (!arg) {
    const current = userCounts.get(ctx.from!.id) ?? DEFAULT_COUNT;
    await ctx.reply(`Текущее количество: ${current}\nИспользуйте /count N (1-${MAX_COUNT}) чтобы изменить.`);
    return;
  }
  const n = parseInt(arg, 10);
  if (isNaN(n) || n < 1 || n > MAX_COUNT) {
    await ctx.reply(`Укажите число от 1 до ${MAX_COUNT}.`);
    return;
  }
  userCounts.set(ctx.from!.id, n);
  await ctx.reply(`Количество генераций установлено: ${n}`);
});

bot.command("save", async (ctx) => {
  const name = ctx.match?.trim();
  if (!name) {
    await ctx.reply("Укажите имя проекта: /save мой_дом");
    return;
  }
  const userId = ctx.from!.id;
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
  await ctx.reply(`Проект «${name}» сохранён. Используйте /load ${name} чтобы вернуться к нему.`);
});

bot.command("load", async (ctx) => {
  const name = ctx.match?.trim();
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (!name) {
    await ctx.reply("Укажите имя проекта: /load мой_дом\nСписок проектов: /projects");
    return;
  }
  if (!projects?.has(name)) {
    await ctx.reply(`Проект «${name}» не найден. Список проектов: /projects`);
    return;
  }

  const project = projects.get(name)!;
  userLastResults.set(userId, {
    imageBuffer: project.imageBuffer,
    prompt: project.lastPrompt,
  });

  await ctx.replyWithPhoto(new InputFile(project.imageBuffer, "project.png"), {
    caption: `Проект «${name}» загружен.\nПоследний промпт: ${project.lastPrompt}\n\nОтветьте на это сообщение с новым описанием, чтобы продолжить.`,
  });
});

bot.command("projects", async (ctx) => {
  const userId = ctx.from!.id;
  const projects = userProjects.get(userId);

  if (!projects || projects.size === 0) {
    await ctx.reply("У вас нет сохранённых проектов.\nИспользуйте /save имя после генерации.");
    return;
  }

  const lines = Array.from(projects.entries()).map(([name, p]) => {
    const date = p.savedAt.toLocaleDateString("ru-RU");
    return `• ${name} (${date}) — ${p.lastPrompt.substring(0, 40)}...`;
  });

  await ctx.reply(`Ваши проекты:\n\n${lines.join("\n")}\n\nИспользуйте /load имя для загрузки.`);
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

  projects.delete(name);
  await ctx.reply(`Проект «${name}» удалён.`);
});

// --- Photo handler: new photo with caption ---
bot.on("message:photo", async (ctx) => {
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
      const last = userLastResults.get(ctx.from!.id);
      if (last) imageBuffer = last.imageBuffer;
    }

    if (imageBuffer) {
      const { count: inlineCount, prompt } = parseCount(text);
      const count = inlineCount || (userCounts.get(ctx.from!.id) ?? DEFAULT_COUNT);
      await ctx.reply(`Итерирую дизайн (${count > 1 ? count + " вариантов" : "1 вариант"})...`);
      await runGeneration(ctx, imageBuffer, prompt, count);
      return;
    }
  }

  // Plain text without reply — use last result if available
  const last = userLastResults.get(ctx.from!.id);
  if (last && !text.startsWith("/")) {
    const { count: inlineCount, prompt } = parseCount(text);
    const count = inlineCount || (userCounts.get(ctx.from!.id) ?? DEFAULT_COUNT);
    await ctx.reply(`Продолжаю работу над последним дизайном (${count > 1 ? count + " вариантов" : "1 вариант"})...`);
    await runGeneration(ctx, last.imageBuffer, prompt, count);
    return;
  }

  await ctx.reply(
    "Как пользоваться ботом:\n\n" +
    "📷 Отправьте фото с подписью — начать новый дизайн\n" +
    "↩️ Ответьте на результат с новым описанием — итерация\n" +
    "💬 Просто напишите текст — продолжить последний дизайн\n\n" +
    "Команды:\n" +
    "/count N — количество вариантов (1-10)\n" +
    "/save имя — сохранить проект\n" +
    "/load имя — загрузить проект\n" +
    "/projects — список проектов\n" +
    "/delete имя — удалить проект"
  );
});

bot.catch((err) => {
  console.error("Bot error:", err);
});

bot.start();
console.log(`Bot is running...`);
console.log(`Thinking model: ${THINKING_MODEL}`);
console.log(`Image model: ${IMAGE_MODEL}`);

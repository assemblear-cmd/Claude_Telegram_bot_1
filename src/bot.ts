import "dotenv/config";
import { Bot, InputFile, InputMediaBuilder } from "grammy";
import { GoogleGenAI, Modality } from "@google/genai";

const THINKING_MODEL = "gemini-3.1-flash-image-preview";
const IMAGE_MODEL = "gemini-3.1-flash-image-preview";
const DEFAULT_COUNT = 1;
const MAX_COUNT = 10;

const userCounts = new Map<number, number>();

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
  const file = await ctx.api.getFile(photo.file_id);
  const fileUrl = `https://api.telegram.org/file/bot${process.env.BOT_TOKEN!}/${file.file_path}`;

  const imageResponse = await fetch(fileUrl);
  const imageBuffer = Buffer.from(await imageResponse.arrayBuffer());

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

  if (successful.length === 1) {
    await ctx.replyWithPhoto(new InputFile(successful[0], "result.png"));
  } else {
    const media = successful.map((buf, i) =>
      InputMediaBuilder.photo(new InputFile(buf, `result_${i + 1}.png`))
    );
    await ctx.replyWithMediaGroup(media);
  }

  if (successful.length < count) {
    await ctx.reply(`Сгенерировано ${successful.length} из ${count} (остальные не удались).`);
  }
});

bot.on("message", async (ctx) => {
  if (!ctx.message.photo) {
    await ctx.reply(
      "Отправьте фото с подписью для генерации.\n" +
      "Можно указать количество в начале: «3 современный дом»\n" +
      "Или задать по умолчанию: /count 4"
    );
  }
});

bot.catch((err) => {
  console.error("Bot error:", err);
});

bot.start();
console.log(`Bot is running...`);
console.log(`Thinking model: ${THINKING_MODEL}`);
console.log(`Image model: ${IMAGE_MODEL}`);

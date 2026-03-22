import "dotenv/config";
import { Bot, InputFile } from "grammy";
import { GoogleGenAI, Modality } from "@google/genai";

const THINKING_MODEL = "gemini-2.5-flash";
const IMAGE_MODEL = "gemini-3.1-flash-image-preview";

const bot = new Bot(process.env.BOT_TOKEN!);
const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });

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

bot.on("message:photo", async (ctx) => {
  const caption = ctx.message.caption ?? "";
  if (!caption.trim()) {
    await ctx.reply("Please send a photo with a text caption describing the desired result.");
    return;
  }

  await ctx.reply("Generating image, please wait...");

  const photo = ctx.message.photo[ctx.message.photo.length - 1];
  const file = await ctx.api.getFile(photo.file_id);
  const fileUrl = `https://api.telegram.org/file/bot${process.env.BOT_TOKEN!}/${file.file_path}`;

  const imageResponse = await fetch(fileUrl);
  const imageBuffer = Buffer.from(await imageResponse.arrayBuffer());

  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const enhancedPrompt = await enhancePrompt(caption);
      const resultBuffer = await generateImage(imageBuffer, enhancedPrompt);
      await ctx.replyWithPhoto(new InputFile(resultBuffer, "result.png"));
      return;
    } catch (err) {
      console.error(`Generation attempt ${attempt} failed:`, err);
      if (attempt === 1) {
        await ctx.reply("Generation failed, retrying...");
      } else {
        await ctx.reply("Generation failed after retry. Please try again later.");
      }
    }
  }
});

bot.on("message", async (ctx) => {
  if (!ctx.message.photo) {
    await ctx.reply("Send me a photo with a caption and I will generate an architectural visualization.");
  }
});

bot.catch((err) => {
  console.error("Bot error:", err);
});

bot.start();
console.log(`Bot is running...`);
console.log(`Thinking model: ${THINKING_MODEL}`);
console.log(`Image model: ${IMAGE_MODEL}`);

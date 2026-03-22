import "dotenv/config";
import { Bot, InputFile } from "grammy";
import Replicate from "replicate";

const PROMPT_PREFIX =
  "Architectural visualization, photorealistic, professional architectural rendering, minimalist style, concrete glass natural wood materials. Building design: ";

const bot = new Bot(process.env.BOT_TOKEN!);
const replicate = new Replicate({ auth: process.env.REPLICATE_API_TOKEN! });

async function generateImage(
  imageUrl: string,
  prompt: string
): Promise<string> {
  const output = await replicate.run("black-forest-labs/flux-pro", {
    input: {
      prompt: PROMPT_PREFIX + prompt,
      image: imageUrl,
    },
  });

  if (typeof output === "string") return output;
  if (Array.isArray(output) && typeof output[0] === "string") return output[0];
  if (output && typeof output === "object" && "output" in (output as any)) {
    const val = (output as any).output;
    if (typeof val === "string") return val;
    if (Array.isArray(val) && typeof val[0] === "string") return val[0];
  }
  throw new Error(`Unexpected Replicate output: ${JSON.stringify(output)}`);
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
  const imageUrl = `https://api.telegram.org/file/bot${process.env.BOT_TOKEN!}/${file.file_path}`;

  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const resultUrl = await generateImage(imageUrl, caption);
      await ctx.replyWithPhoto(new InputFile(new URL(resultUrl)));
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
console.log("Bot is running...");

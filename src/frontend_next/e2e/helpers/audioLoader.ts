/**
 * 測試音訊載入工具
 * 從 fixtures/audio/ 讀取預生成的 MP3 並轉為 base64。
 */
import { readFile } from 'fs/promises'
import path from 'path'

const FIXTURES_DIR = path.join(__dirname, '..', 'fixtures', 'audio')

export async function loadAudioBase64(name: string): Promise<string> {
  const filePath = path.join(FIXTURES_DIR, `${name}.mp3`)
  const buffer = await readFile(filePath)
  return buffer.toString('base64')
}

/** 所有預定義的測試語音 key */
export const AUDIO_KEYS = [
  'single_item',      // 單品點餐
  'multi_item',       // 多品點餐
  'add_more',         // 再加一個
  'remove_item',      // 移除品項
  'checkout',         // 結帳
  'dine_in',          // 內用
  'take_out',         // 外帶
  'cash_payment',     // 現金付款
  'inquiry_drinks',   // 詢問飲料
  'out_of_stock',     // 售完品項
] as const

export type AudioKey = typeof AUDIO_KEYS[number]

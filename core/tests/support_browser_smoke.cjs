// Run only against an isolated local database; credentials provided through env.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.SUPPORT_TEST_BROWSER || 'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1400,height:900}});
    const failures=[];page.on('pageerror', e=>failures.push(e.message));
    const base=process.env.SUPPORT_TEST_URL || 'http://127.0.0.1:8031';
    await page.goto(base);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('header [data-open=support]').click();
    const form=page.locator('dialog [data-support-form]');
    await form.getByLabel('Email').fill('qa@example.test');
    await form.getByLabel('Как к Вам обращаться').fill('Тест интерфейса');
    await form.getByLabel('Ваш вопрос').fill('Как сохранить и перенести архив?');
    await form.getByRole('button',{name:'Отправить',exact:true}).click();
    await page.getByText('Сообщение отправлено',{exact:true}).waitFor();
    await page.locator('#info-dialog .close').click();
    await page.setViewportSize({width:1400,height:900});
    await page.goto(base+'/support');
    await page.getByLabel('Имя пользователя').fill(process.env.SUPPORT_TEST_USER);
    await page.getByLabel('Пароль').fill(process.env.SUPPORT_TEST_PASSWORD);
    await page.getByRole('button',{name:'Войти',exact:true}).click();
    await page.waitForURL(/\/support\/?$/);
    await page.locator('[data-ticket-url]').first().click();
    await page.locator('#ticket-dialog').waitFor({state:'visible'});
    await page.locator('#ticket-dialog').getByRole('button',{name:'В работу',exact:true}).click();
    await page.waitForURL(/\/support\/tickets\/\d+$/);
    await page.getByLabel('Ответ пользователю').fill('Для переноса сохраните ZIP через меню архива.');
    await page.getByRole('button',{name:'Отправить ответ'}).click();
    await page.getByText('Ответ отправлен на Email и сохранён.',{exact:true}).waitFor();
    await page.locator('.support-badge.answered').waitFor();
    await page.goto(base+'/support');
    await page.locator('input[name=q]').fill('qa@example.test');
    await page.getByRole('button',{name:'Найти',exact:true}).click();
    assert.ok(await page.locator('[data-ticket-url]').count());
    if(process.env.SUPPORT_TEST_SCREENSHOT) await page.screenshot({path:process.env.SUPPORT_TEST_SCREENSHOT,fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.deepEqual(failures,[]);
    console.log('Public form, staff login, details modal, status, reply, search and mobile overflow: OK');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

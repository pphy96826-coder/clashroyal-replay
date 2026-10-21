package local.royale.replay.android;

import android.app.Activity;
import android.content.Intent;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Handler;
import android.view.View;
import android.webkit.*;
import android.widget.*;
import androidx.webkit.ProxyConfig;
import androidx.webkit.ProxyController;
import androidx.webkit.WebViewFeature;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executor;
import org.json.JSONObject;

/** No JS/native bridge. Capture only the user-selected RoyaleAPI replay DOM. */
public final class BrowserActivity extends Activity {
    private WebView page;
    private EditText address;
    private TextView status;
    private Button capture;
    private volatile boolean ready,closed;
    private boolean capturing;
    private double speed;
    private PlaybackHandoff handoff;
    private final Runnable handoffCheck=new Runnable(){public void run(){if(!closed){if(handoff!=null)handoff.check();handler.postDelayed(this,1000);}}};
    private final Handler handler=new Handler();
    @Override public void onCreate(Bundle state){
        super.onCreate(state);setTitle("RoyaleAPI · 选择对局");
        speed=getIntent().getDoubleExtra("speed",1);
        handoff=new PlaybackHandoff(this);handler.post(handoffCheck);
        final LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(16,18,16,12);
        TextView title=new TextView(this);title.setText("RoyaleAPI · 选择对局后点播放本页");title.setTextSize(20);root.addView(title);
        address=new EditText(this);address.setSingleLine(true);address.setText("https://royaleapi.com/");root.addView(address);
        Button open=new Button(this);open.setText("打开网址");open.setOnClickListener(new View.OnClickListener(){public void onClick(View v){navigate(address.getText().toString());}});root.addView(open);
        capture=new Button(this);capture.setText("播放本页回放");capture.setEnabled(false);capture.setOnClickListener(new View.OnClickListener(){public void onClick(View v){capture();}});root.addView(capture);
        status=new TextView(this);status.setText("仅内置浏览器直连；不修改电脑、Clash 或安卓系统网络。登录与网页验证请自行操作。");root.addView(status);setContentView(root);
        try{
            if(!WebViewFeature.isFeatureSupported(WebViewFeature.PROXY_OVERRIDE))throw new IOException("此 WebView 不支持应用内直连配置；未修改系统网络，可先使用本地 HTML。");
            page=new WebView(this);
            WebSettings settings=page.getSettings();settings.setBlockNetworkLoads(true);
            settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setAllowFileAccessFromFileURLs(false);settings.setAllowUniversalAccessFromFileURLs(false);
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);settings.setJavaScriptCanOpenWindowsAutomatically(false);settings.setSupportMultipleWindows(false);
            settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
            page.setWebViewClient(new WebViewClient(){
                @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                    String url=request.getUrl().toString();
                    if(!BrowserPolicy.allowed(url)){status.setText("该跳转未打开。Google 登录可能不支持内置浏览器；可使用普通浏览器保存 HTML 再导入。");return true;}
                    capture.setEnabled(false);return !ready;
                }
                @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                    if(!ready||!BrowserPolicy.allowed(request.getUrl().toString()))return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));
                    return null;
                }
                @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){capture.setEnabled(false);}
                @Override public void onPageFinished(WebView view,String url){
                    address.setText(url);capture.setEnabled(ready&&!capturing&&!BrowserPolicy.replayTag(url).isEmpty());
                    status.setText("内置浏览器直连。找到 Replay 详情页后点“播放本页回放”；不会读取密码或 Cookie。");
                }
                @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){if(request.isForMainFrame()){capture.setEnabled(false);status.setText("网页直连未加载："+error.getDescription()+"。未修改系统网络；也可导入已保存 HTML。");}}
                @Override public void onReceivedSslError(WebView view,SslErrorHandler handle,SslError error){handle.cancel();capture.setEnabled(false);status.setText("证书校验未通过；未忽略证书错误。");}
            });
            root.addView(page,new LinearLayout.LayoutParams(-1,0,1));
            // Process-local WebView override only. Never writes a system proxy,
            // VPN, desktop Clash rule, DNS setting or any other application's route.
            ProxyConfig proxy=new ProxyConfig.Builder().addDirect().removeImplicitRules().build();
            ProxyController.getInstance().setProxyOverride(proxy,new Executor(){public void execute(Runnable task){handler.post(task);}},new Runnable(){public void run(){
                if(closed)return;
                ready=true;page.getSettings().setBlockNetworkLoads(false);navigate("https://royaleapi.com/");
            }});
        }catch(Exception e){status.setText(e.getMessage());}
    }
    private void navigate(String url){
        if(!ready||page==null){status.setText("内置浏览器直连设置尚未完成；未访问网址。返回主界面仍可导入 HTML。");return;}
        if(!BrowserPolicy.allowed(url)){status.setText("仅允许指定的 HTTPS RoyaleAPI 网页与资源；不会打开其他协议或本地文件。");return;}
        capture.setEnabled(false);status.setText("正在直连加载…");page.loadUrl(url);
    }
    private void capture(){
        if(!OverlayAccess.ensure(this)){status.setText("请先在系统页面允许悬浮进度卡，返回后重新点播放本页。");return;}
        final String url=page==null?"":page.getUrl();final String tag=BrowserPolicy.replayTag(url);
        if(tag.isEmpty()||!ready||capturing)return;
        capturing=true;capture.setEnabled(false);status.setText("正在读取当前回放页；不会上传 HTML…");
        page.evaluateJavascript("(()=>{if(location.origin!=='https://royaleapi.com'&&location.origin!=='https://www.royaleapi.com')return null;const root=document.querySelector('.battle_replay[data-tag]');if(!root||!root.querySelector('[data-t]'))return null;const html=document.documentElement.outerHTML;if(html.length>26214400)return null;return {url:location.href,html:html};})()",new ValueCallback<String>(){public void onReceiveValue(String value){try{
            if(!url.equals(page.getUrl()))throw new IOException("网页已切换，请重新选择本页");
            JSONObject snapshot=new JSONObject(value);
            if(!url.equals(snapshot.getString("url")))throw new IOException("网页来源已变化");
            byte[] bytes=snapshot.getString("html").getBytes(StandardCharsets.UTF_8);
            ReplaySource.Info parsed=MainActivity.checkedSource(bytes);
            if(!tag.equals(parsed.tag))throw new IOException("网址与回放编号不一致");
            boolean started=PlaybackService.submitOrQueue(BrowserActivity.this,bytes,speed);
            status.setText(started?"正在本机准备；确认原生回放实际步进后才切到游戏。可下拉通知栏查看状态。":"本场已加入待播队列，尚未播放；当前回放不受影响。结束后点“播放下一个”。");
        }catch(Exception e){status.setText("未开始播放："+e.getMessage()+"。请确认已登录并打开完整 Replay 详情页。");}finally{capturing=false;capture.setEnabled(!BrowserPolicy.replayTag(page.getUrl()).isEmpty());}}});
    }
    @Override public void onBackPressed(){if(page!=null&&page.canGoBack()){capture.setEnabled(false);page.goBack();}else super.onBackPressed();}
    @Override protected void onResume(){super.onResume();PlaybackService.consoleVisible();if(handoff!=null)handoff.resume();}
    @Override protected void onPause(){if(handoff!=null)handoff.pause();super.onPause();}
    @Override protected void onDestroy(){closed=true;ready=false;if(page!=null){page.getSettings().setBlockNetworkLoads(true);page.stopLoading();page.destroy();}super.onDestroy();}
}

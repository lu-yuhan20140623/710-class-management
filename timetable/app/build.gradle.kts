import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 令牌不入库：从 gitignore 的 local.properties 注入，源码里不出现明文
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
val relayToken = localProps.getProperty("relay.token", "")

android {
    namespace = "com.example.timetable"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.example.timetable"
        minSdk = 24
        targetSdk = 36
        versionCode = 2
        versionName = "1.2.0"
        buildConfigField("String", "RELAY_TOKEN", "\"$relayToken\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.18.0")
}

// Wind-animated grass.
//
// Lit with a single wrapped-lambert term rather than through UniversalFragmentPBR:
// grass is a hundred thousand tiny blades, and a full PBR evaluation per fragment
// buys nothing on geometry this thin. It still takes the main light's colour and
// direction so the field brightens and darkens with the rest of the scene.
//
// The sway is driven entirely in the vertex stage, so the CPU uploads nothing per
// frame. Amplitude scales with a per-vertex height factor carried in vertex
// colour, which is what keeps the blade roots planted while the tips whip.

Shader "VRAR/GrassWind"
{
    Properties
    {
        _BaseColor ("Grass Colour", Color) = (0.32, 0.46, 0.20, 1)
        _TipColor ("Tip Colour", Color) = (0.48, 0.62, 0.28, 1)
        _WindStrength ("Wind Strength", Range(0, 3)) = 0.55
        _WindSpeed ("Wind Speed", Range(0, 6)) = 1.4
        _WindDirection ("Wind Direction", Vector) = (0.8, 0, 0.6, 0)
        _FadeStart ("Fade Start (m)", Float) = 55
        _FadeEnd ("Fade End (m)", Float) = 110
        _Ambient ("Ambient", Range(0, 1)) = 0.42
        _BladeHeight ("Blade Height (m)", Float) = 1
    }

    SubShader
    {
        Tags { "RenderType" = "TransparentCutout" "RenderPipeline" = "UniversalPipeline" "Queue" = "AlphaTest" }

        Pass
        {
            Name "GrassForward"
            Tags { "LightMode" = "UniversalForward" }

            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_fog

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _TipColor;
                float4 _WindDirection;
                float _WindStrength, _WindSpeed, _FadeStart, _FadeEnd, _Ambient, _BladeHeight;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float4 color      : COLOR;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float4 color      : TEXCOORD0;
                float3 normalWS   : TEXCOORD1;
                float3 positionWS : TEXCOORD2;
                float  fogCoord   : TEXCOORD3;
                float  height     : TEXCOORD4;
            };

            Varyings Vert(Attributes input)
            {
                Varyings output;

                // Vertex colour carries the layout: .rgb is the blade's own
                // gradient, .a is unused. The height factor is reconstructed from
                // the local Y rather than shipped separately.
                float3 positionWS = TransformObjectToWorld(input.positionOS.xyz);
                float heightFactor = saturate(input.positionOS.y / _BladeHeight);

                // Two incommensurate waves read as gusting rather than as a
                // metronome, and the phase is taken from world position so the
                // field travels across the ground instead of pulsing in place.
                float2 phase = positionWS.xz * 0.35;
                float gust = sin(_Time.y * _WindSpeed + phase.x + phase.y * 0.6) * 0.6
                           + sin(_Time.y * _WindSpeed * 1.73 + phase.y * 1.9) * 0.4;

                float sway = gust * _WindStrength * heightFactor * heightFactor;
                positionWS.xz += normalize(_WindDirection.xz + 1e-5) * sway;

                // Bend shortens the blade: without this the tips slide sideways
                // and the grass appears to stretch.
                positionWS.y -= abs(sway) * 0.3 * heightFactor;

                output.positionCS = TransformWorldToHClip(positionWS);
                output.positionWS = positionWS;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.color = input.color;
                output.height = heightFactor;
                output.fogCoord = ComputeFogFactor(output.positionCS.z);
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                Light mainLight = GetMainLight();

                // Wrapped lambert: grass is thin and translucent, so it lights on
                // the side facing away from the sun too.
                half wrapped = saturate(dot(normalize(input.normalWS), mainLight.direction) * 0.5h + 0.5h);
                half lighting = _Ambient + wrapped * mainLight.color;

                half3 albedo = lerp(_BaseColor.rgb, _TipColor.rgb, input.height) * input.color.rgb;
                half3 colour = albedo * lighting;

                // Fade out with distance so the far field hands over to the
                // terrain texture rather than turning into aliased noise.
                float distanceToCamera = distance(input.positionWS, _WorldSpaceCameraPos);
                half alpha = 1.0h - saturate((distanceToCamera - _FadeStart) / max(0.001, _FadeEnd - _FadeStart));

                colour = MixFog(colour, input.fogCoord);
                return half4(colour, alpha * _BaseColor.a);
            }
            ENDHLSL
        }
    }
}
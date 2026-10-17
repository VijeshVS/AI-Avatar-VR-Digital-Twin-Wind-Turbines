// URP forward-lit terrain shader: three ground layers blended per vertex.
//
// Why not Unity's Terrain component: a heightmap terrain large enough to read as
// a landscape spends more memory than this project's whole 8 GB budget allows
// (PRD NFR-1.4). A plain mesh with per-vertex layer weights costs a fraction of
// that, and lets the weights be authored on the CPU from height and slope instead
// of from splat maps.
//
// Weights arrive in vertex colour: r = grass, g = rock, b = dirt. Textures are
// sampled with world-space UVs so tiling never stretches with terrain size.

Shader "VRAR/TerrainBlend"
{
    Properties
    {
        _GrassDiff ("Grass Diffuse", 2D) = "white" {}
        _GrassNormal ("Grass Normal", 2D) = "bump" {}
        _RockDiff ("Rock Diffuse", 2D) = "white" {}
        _RockNormal ("Rock Normal", 2D) = "bump" {}
        _DirtDiff ("Dirt Diffuse", 2D) = "white" {}
        _DirtNormal ("Dirt Normal", 2D) = "bump" {}
        _GrassTile ("Grass Tile (m)", Float) = 22
        _RockTile ("Rock Tile (m)", Float) = 26
        _DirtTile ("Dirt Tile (m)", Float) = 34
        _NormalStrength ("Normal Strength", Range(0, 2)) = 0.85
        _MacroScale ("Macro Variation Scale", Float) = 0.0035
        _MacroStrength ("Macro Variation", Range(0, 1)) = 0.22
        _GrassTint ("Grass Tint", Color) = (0.78, 1.18, 0.48)
        _BaseY ("Base Y", Float) = 0
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "Queue" = "Geometry" }

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_fog
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile _ _ADDITIONAL_LIGHTS_VERTEX _ADDITIONAL_LIGHTS
            #pragma multi_compile _ _SHADOWS_SOFT
            #pragma multi_compile _ _SPECULAR_SETUP

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            TEXTURE2D(_GrassDiff);   SAMPLER(sampler_GrassDiff);
            TEXTURE2D(_RockDiff);    SAMPLER(sampler_RockDiff);
            TEXTURE2D(_DirtDiff);    SAMPLER(sampler_DirtDiff);
            TEXTURE2D(_GrassNormal); SAMPLER(sampler_GrassNormal);
            TEXTURE2D(_RockNormal);  SAMPLER(sampler_RockNormal);
            TEXTURE2D(_DirtNormal);  SAMPLER(sampler_DirtNormal);

            CBUFFER_START(UnityPerMaterial)
                float4 _GrassDiff_ST, _RockDiff_ST, _DirtDiff_ST;
                float4 _GrassNormal_ST, _RockNormal_ST, _DirtNormal_ST;
                float _GrassTile, _RockTile, _DirtTile;
                float4 _GrassTint;
                float _NormalStrength, _MacroScale, _MacroStrength, _BaseY;
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
                float3 positionWS : TEXCOORD0;
                float3 normalWS   : TEXCOORD1;
                float4 weights    : TEXCOORD2;
                float  fogCoord   : TEXCOORD3;
            };

            Varyings Vert(Attributes input)
            {
                Varyings output;
                VertexPositionInputs positions = GetVertexPositionInputs(input.positionOS.xyz);
                output.positionCS = positions.positionCS;
                output.positionWS = positions.positionWS;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.weights = input.color;
                output.fogCoord = ComputeFogFactor(positions.positionCS.z);
                return output;
            }

            // Poly Haven's *_nor_gl maps are DXT5nm-style packed, which is exactly
            // what UnpackNormalScale expects. It takes a float4 because it takes
            // the scale in .w, so the sample must be passed whole rather than
            // sliced to .xyz.
            float3 UnpackDetail(float4 packed)
            {
                return UnpackNormalScale(packed, _NormalStrength).xyz;
            }

            float4 Frag(Varyings input) : SV_Target
            {
                float3 weights = input.weights.rgb;
                float total = max(weights.r + weights.g + weights.b, 0.0001);
                weights /= total;

                // World-space planar projection. The terrain is authored in the XZ
                // plane and never folds underneath itself, so this costs one
                // sample per layer instead of the three triplanar would need.
                float2 uv = input.positionWS.xz;

                float3 albedo = float3(0.0, 0.0, 0.0);
                float3 detail = float3(0.0, 0.0, 0.0);

                if (weights.r > 0.001)
                {
                    float2 uvg = uv / _GrassTile;
                    albedo += SAMPLE_TEXTURE2D(_GrassDiff, sampler_GrassDiff, uvg).rgb * _GrassTint.rgb * weights.r;
                    detail += UnpackDetail(SAMPLE_TEXTURE2D(_GrassNormal, sampler_GrassNormal, uvg)) * weights.r;
                }

                if (weights.g > 0.001)
                {
                    float2 uvr = uv / _RockTile;
                    albedo += SAMPLE_TEXTURE2D(_RockDiff, sampler_RockDiff, uvr).rgb * weights.g;
                    detail += UnpackDetail(SAMPLE_TEXTURE2D(_RockNormal, sampler_RockNormal, uvr)) * weights.g;
                }

                if (weights.b > 0.001)
                {
                    float2 uvd = uv / _DirtTile;
                    albedo += SAMPLE_TEXTURE2D(_DirtDiff, sampler_DirtDiff, uvd).rgb * weights.b;
                    detail += UnpackDetail(SAMPLE_TEXTURE2D(_DirtNormal, sampler_DirtNormal, uvd)) * weights.b;
                }

                // Low-frequency multiplier so the tile repetition is not obvious
                // across a kilometre of ground. Uses the grass map purely as a
                // source of cheap low-frequency noise.
                float3 macro = SAMPLE_TEXTURE2D(_GrassDiff, sampler_GrassDiff, uv * _MacroScale).rgb;
                albedo = lerp(albedo, albedo * macro * 2.0, _MacroStrength);

                float3 normalTS = normalize(detail);

                // GetVertexNormalInputs takes the tangent-space normal as a float4
                // (xyz normal, w handedness) and returns a struct rather than a
                // vector, so both halves are unpicked here.
                half4 tangentNormal = half4(normalTS, 0.0h);
                VertexNormalInputs shadingNormal = GetVertexNormalInputs(input.normalWS, tangentNormal);

                InputData inputData = (InputData)0;
                inputData.positionWS = input.positionWS;
                inputData.normalWS = shadingNormal.normalWS;
                inputData.viewDirectionWS = GetWorldSpaceNormalizeViewDir(input.positionWS);
                inputData.shadowCoord = TransformWorldToShadowCoord(input.positionWS);
                inputData.fogCoord = input.fogCoord;
                inputData.bakedGI = SampleSH(inputData.normalWS);
                inputData.normalizedScreenSpaceUV = GetNormalizedScreenSpaceUV(input.positionCS);
                inputData.shadowMask = half4(1, 1, 1, 1);

                SurfaceData surface = (SurfaceData)0;
                surface.albedo = albedo;
                surface.metallic = 0.0;
                surface.smoothness = 0.06;
                surface.normalTS = normalTS;
                surface.occlusion = 1.0;
                surface.emission = float3(0, 0, 0);
                surface.alpha = 1.0;

                return UniversalFragmentPBR(inputData, surface);
            }
            ENDHLSL
        }
    }

    FallBack "Universal Render Pipeline/Lit"
}